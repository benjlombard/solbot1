"""
Token Sync Service
Main orchestrator service that coordinates all token synchronization activities.
"""
import time
import asyncio
import logging
import signal
import sys
from typing import Optional, Dict, Any
from datetime import datetime, timedelta

from ..database.connection import DatabaseConnection
from ..database.token_repository import TokenRepository
from ..database.queue_repository import QueueRepository
from ..database.history_repository import HistoryRepository
from ..api_clients.dexscreener_client import DexScreenerClient
from ..processors.batch_processor import BatchProcessor
from ..monitoring.cycle_logger import CycleLogger
from ..monitoring.api_tracker import ApiTracker


class SyncService:
    """
    Main synchronization service that orchestrates all token data operations
    """
    
    def __init__(self, config, logger: Optional[logging.Logger] = None):
        self.config = config
        self.logger = logger or logging.getLogger(__name__)
        self.running = False
        
        # Initialize database connection
        self.db_connection = DatabaseConnection(
            db_path=config.database.get_full_path(),
            timeout=config.database.timeout,
            logger=self.logger
        )
        
        # Initialize repositories
        self.history_repo = HistoryRepository(self.db_connection, self.config, self.logger)
        self.queue_repo = QueueRepository(self.db_connection, self.logger)
        self.token_repo = TokenRepository(self.db_connection, self.history_repo, self.logger)
        self.api_tracker = ApiTracker(
            db_connection=self.db_connection, 
            logger=self.logger
        )

        self.cycle_logger = CycleLogger(logger=self.logger)
        # Initialize API clients
        self.dex_client = DexScreenerClient(logger=self.logger, api_tracker=self.api_tracker)
        
        # Initialize processors
        self.batch_processor = BatchProcessor(
            dex_client=self.dex_client,
            token_repo=self.token_repo,
            queue_repo=self.queue_repo,
            config=config,
            logger=self.logger
        )
        
        # Initialize historization processor if available
        self.historization_processor = None
        try:
            from ..processors.historization_processor import HistorizationProcessor
            self.historization_processor = HistorizationProcessor(
                db_connection=self.db_connection,
                config=config,
                logger=self.logger
            )
            self.logger.debug("✅ Historization processor initialized")
        except ImportError:
            self.logger.warning("⚠️ Historization processor not available")
        
        self.last_processed_created_at: Optional[str] = None
        self.initial_population_done: bool = False

        # Statistics
        self.stats = {
            'processed_tokens': 0,
            'successful_updates': 0,
            'failed_updates': 0,
            'cycles_completed': 0,
            'start_time': None
        }
        
        # Cycle management
        self.current_sync_cycle_id = None
        self.cycle_count = 0
        self._cycle_started = False  # Flag pour éviter double logging
        
        pass
    
    def get_api_statistics(self) -> Dict[str, Any]:
        """Get detailed API statistics"""
        try:
            return {
                'api_tracker_stats': self.api_tracker.get_stats(),
                'global_stats': self.api_tracker.get_global_stats(),
                'health_report': self.api_tracker.get_api_health_report(),
                'top_apis_by_calls': self.api_tracker.get_top_apis(limit=10, sort_by='calls'),
                'top_apis_by_duration': self.api_tracker.get_top_apis(limit=5, sort_by='duration'),
                'top_apis_by_failures': self.api_tracker.get_top_apis(limit=5, sort_by='failures')
            }
        except Exception as e:
            self.logger.error(f"Error getting API statistics: {e}")
            return {'error': str(e)}

    def start(self):
        """Start the continuous synchronization service"""
        self.logger.info("🚀 Starting Token Sync Service...")
        
        # Check database health
        if not self.db_connection.check_health():
            self.logger.error("❌ Database health check failed. Stopping service.")
            return
        
        self.running = True
        self.stats['start_time'] = time.time()
        
        try:
            while self.running:
                try:
                    self._run_sync_cycle()
                    self.stats['cycles_completed'] += 1
                    
                    if self.running:
                        self._wait_for_next_cycle()
                        
                except KeyboardInterrupt:
                    self.logger.info("Received keyboard interrupt")
                    break
                except Exception as e:
                    self.logger.error(f"Unexpected error in sync cycle: {e}", exc_info=True)
                    # Wait a bit before retrying to avoid rapid failures
                    if self.running:
                        time.sleep(30)
                    
        except Exception as e:
            self.logger.error(f"Fatal error in main loop: {e}", exc_info=True)
        finally:
            self.stop()

        
    def _run_sync_cycle(self):
        """Run one complete synchronization cycle"""
        self.cycle_count += 1
        cycle_id = self._start_sync_cycle()
        
        try:
            # 1. Process new tokens from queue
            new_tokens_result = self._process_new_tokens()
            new_tokens_processed = new_tokens_result['successful']
            historized_count = new_tokens_result['historized']
            stubs_count = new_tokens_result['stubs']
            new_tokens_added = new_tokens_result.get('new_tokens_added_to_queue', 0)

            self.cycle_logger.record_operation('new_tokens', new_tokens_processed)

            if historized_count > 0:
                self.cycle_logger.record_operation('historized_tokens', historized_count)
            if stubs_count > 0:
                self.cycle_logger.record_operation('stubs_created', stubs_count)

            if new_tokens_processed > 0:
                self.logger.info(f"➕ Processed {new_tokens_processed} new tokens ({historized_count} historized, {stubs_count} stubs)")
            
            # 2. Update existing token prices
            self.logger.debug("🔄 Updating existing token prices...")
            prices_updated = self._update_existing_prices()
            self.cycle_logger.record_operation('updated_tokens', prices_updated)
            
            if prices_updated > 0:
                self.logger.info(f"🔄 Updated {prices_updated} token prices")
            
            # 3. Historization améliorée
            self.logger.debug("📈 Running periodic historization...")
            periodic_historized = self._run_historization_improved()
            if periodic_historized > 0:
                # Ajouter au compteur existant
                self.cycle_logger.add_operation_count('historized_tokens', periodic_historized)
                self.logger.info(f"📈 Additional periodic historization: {periodic_historized} tokens")
            
            # 4. Periodic tasks (every N cycles)
            if self.cycle_count % 5 == 0:
                self.logger.debug("⚙️ Running periodic tasks...")
                self._run_periodic_tasks()
            
            # Update statistics
            total_processed = new_tokens_processed + prices_updated
            total_historized = historized_count + periodic_historized
            
            self.stats['processed_tokens'] += total_processed
            self.stats['successful_updates'] += total_processed  # Assuming all processed are successful for now
            
            # Log cycle completion
            if total_processed > 0 or total_historized > 0 or stubs_count > 0 or new_tokens_added > 0:
                self.logger.info(
                    f"✅ CYCLE {self.cycle_count} COMPLETED: "
                    f"{new_tokens_processed} processed, {prices_updated} updated, "
                    f"{total_historized} historized, {stubs_count} stubs, "
                    f"{new_tokens_added} new tokens added to queue"
                )
            else:
                self.logger.debug(f"✅ CYCLE {self.cycle_count} COMPLETED: No tokens to process")
            
            # Record API calls from this cycle
            if hasattr(self.api_tracker, 'get_stats'):
                api_stats = self.api_tracker.get_stats()
                for api_name, stats in api_stats.items():
                    if stats.get('calls_1m', 0) > 0:
                        self.cycle_logger.record_api_call(
                            api_name, 
                            stats.get('calls_1m', 0),
                            stats.get('avg_duration_1m', 0)
                        )
            
        except KeyboardInterrupt:
            self.logger.info("🛑 Keyboard interrupt received during cycle")
            raise
        except Exception as e:
            self.logger.error(f"❌ Error in sync cycle {cycle_id}: {e}", exc_info=True)
            self.cycle_logger.record_error(str(e))
            self.stats['failed_updates'] += 1
            
            # Don't re-raise to allow service to continue
            # but log the error for investigation
            
        finally:
            # Always end the cycle properly
            try:
                self._end_sync_cycle(cycle_id)
            except Exception as e:
                self.logger.error(f"Error ending sync cycle {cycle_id}: {e}")
    
    def _process_new_tokens(self) -> int:
        """Process new tokens from the queue"""
        self.logger.debug("📥 Processing new tokens from queue...")
        
        # # Get pending tokens from queue
        # pending_tokens = self.queue_repo.get_pending_tokens(
        #     self.config.processing.batch_size_new_tokens
        # )
        
        # if not pending_tokens:
        #     self.logger.debug("No new tokens in queue to process")
        #     return 0
        
        # self.logger.info(f"📊 Processing {len(pending_tokens)} new tokens")

        # successful_count, historized_count, stubs_count = asyncio.run(
        #     self.batch_processor.process_new_tokens_from_queue(pending_tokens)
        # )

        # return {
        #     'successful': successful_count,
        #     'historized': historized_count,
        #     'stubs': stubs_count
        # }

        # 1. D'abord traiter la queue existante
        queue_result = self._process_tokens_from_queue()
        
        # 2. Ensuite ajouter de nouveaux tokens depuis les transactions
        new_tokens_added = self._add_new_tokens_from_transactions()
        
        return {
            'successful': queue_result['successful'],
            'historized': queue_result['historized'], 
            'stubs': queue_result['stubs'],
            'new_tokens_added_to_queue': new_tokens_added
        }

    
    def _process_tokens_from_queue(self) -> Dict[str, Any]:
        """Process existing tokens from queue"""
        pending_tokens = self.queue_repo.get_pending_tokens(
            self.config.processing.batch_size_new_tokens
        )
        
        if not pending_tokens:
            return {'successful': 0, 'historized': 0, 'stubs': 0}
        
        self.logger.info(f"📊 Processing {len(pending_tokens)} tokens from queue")
        
        successful_count, historized_count, stubs_count = asyncio.run(
            self.batch_processor.process_new_tokens_from_queue(pending_tokens)
        )
        
        return {
            'successful': successful_count,
            'historized': historized_count,
            'stubs': stubs_count
        }

    def _add_new_tokens_from_transactions(self) -> int:
        """Add new tokens from transactions to queue"""
        try:
            # Population initiale si pas encore faite
            if not self.initial_population_done:
                # Vérifier d'abord si la queue contient déjà des tokens actifs
                if not self.queue_repo.is_queue_empty():
                    # La queue contient déjà des tokens actifs, pas besoin de population initiale
                    total_items = self.queue_repo.get_total_queue_size()
                    self.logger.info(f"🔍 Queue already contains active items ({total_items} total), skipping initial population")
                    self.initial_population_done = True
                    
                    # Récupérer le timestamp le plus récent des tokens existants
                    self.last_processed_created_at = self.token_repo.get_most_recent_token_timestamp()
                    if self.last_processed_created_at:
                        self.logger.info(f"📅 Using existing most recent timestamp: {self.last_processed_created_at}")
                    else:
                        self.logger.warning("⚠️ No recent timestamp found in tokens table")
                    
                    return 0
                else:
                    # La queue est vide, faire la population initiale
                    self.logger.info("🔄 Queue is empty, proceeding with initial population")
                    return self._do_initial_population()
            
            # Sinon, rechercher les nouveaux tokens depuis le dernier timestamp
            return self._add_tokens_since_last_timestamp()
            
        except Exception as e:
            self.logger.error(f"Error adding new tokens from transactions: {e}")
            return 0

    def _do_initial_population(self) -> int:
        """Faire la population initiale depuis les transactions"""
        try:
            limit = self.config.processing.initial_population_limit
            
            self.logger.info(f"🚀 Starting initial population with {limit} tokens (queue is empty)")
            
            token_addresses, most_recent_created_at = self.token_repo.get_initial_population_tokens(limit)
            
            if token_addresses:
                added_count = self.queue_repo.add_tokens_to_queue(
                    list(token_addresses),
                    source="initial_population"
                )
                
                # Sauvegarder le timestamp le plus récent
                self.last_processed_created_at = most_recent_created_at
                self.initial_population_done = True
                
                self.logger.info(
                    f"✅ Initial population: {added_count} tokens added to queue, "
                    f"last created_at: {most_recent_created_at}"
                )
                
                return added_count
            else:
                self.initial_population_done = True
                self.logger.info("🔍 No tokens found for initial population")
                return 0
                
        except Exception as e:
            self.logger.error(f"Error in initial population: {e}")
            return 0

    def debug_next_cycle(self):
        """
        Active les logs de debug pour le prochain cycle uniquement
        """
        # Augmenter temporairement le niveau de logs
        original_level = self.logger.level
        self.logger.setLevel(logging.DEBUG)
        
        try:
            # Faire un diagnostic complet
            diagnosis = self.diagnose_token_discovery()
            
            self.logger.info("=== 🔍 DIAGNOSTIC TOKEN DISCOVERY ===")
            for key, value in diagnosis.items():
                self.logger.info(f"{key}: {value}")
            
            # Exécuter un cycle avec logs détaillés
            self.logger.info("=== 🔍 EXECUTING DEBUG CYCLE ===")
            self._run_sync_cycle()
            
        finally:
            # Restaurer le niveau de logs original
            self.logger.setLevel(original_level)

    def diagnose_token_discovery(self) -> Dict[str, Any]:
        """
        Fonction de diagnostic complète pour comprendre pourquoi les nouveaux tokens 
        ne sont pas découverts - VERSION CORRIGÉE AVEC GESTION DES FORMATS
        """
        diagnosis = {}
        
        try:
            with self.db_connection.get_connection_context() as conn:
                cursor = conn.cursor()
                
                # 1. État de la queue
                cursor.execute("SELECT COUNT(*) FROM token_processing_queue WHERE status = 'pending'")
                pending_count = cursor.fetchone()[0]
                
                cursor.execute("SELECT COUNT(*) FROM token_processing_queue")
                total_queue_count = cursor.fetchone()[0]
                
                diagnosis['queue_status'] = {
                    'pending': pending_count,
                    'total': total_queue_count,
                    'is_empty': pending_count == 0
                }
                
                # 2. Transactions récentes
                cursor.execute("""
                    SELECT COUNT(*) FROM transactions 
                    WHERE created_at > (strftime('%s', 'now') - 3600)
                """)
                recent_transactions_1h = cursor.fetchone()[0]
                
                cursor.execute("""
                    SELECT COUNT(*) FROM transactions 
                    WHERE created_at > (strftime('%s', 'now') - 86400)
                """)
                recent_transactions_24h = cursor.fetchone()[0]
                
                cursor.execute("SELECT MAX(created_at) FROM transactions")
                latest_transaction_unix = cursor.fetchone()[0]
                
                # Convertir le timestamp Unix en date lisible
                latest_transaction_readable = None
                if latest_transaction_unix:
                    try:
                        latest_transaction_readable = datetime.fromtimestamp(latest_transaction_unix).isoformat()
                    except:
                        latest_transaction_readable = "Error converting timestamp"
                
                diagnosis['transactions_status'] = {
                    'recent_transactions_1h': recent_transactions_1h,
                    'recent_transactions_24h': recent_transactions_24h,
                    'latest_transaction_unix': latest_transaction_unix,
                    'latest_transaction_readable': latest_transaction_readable,
                    'last_processed_created_at': self.last_processed_created_at
                }
                
                # 3. Gestion des timestamps pour comparaisons
                if self.last_processed_created_at:
                    try:
                        # Convertir le format datetime en timestamp Unix
                        dt = datetime.fromisoformat(self.last_processed_created_at.replace('Z', ''))
                        since_timestamp_unix = int(dt.timestamp())
                        
                        diagnosis['timestamp_conversion'] = {
                            'last_processed_datetime': self.last_processed_created_at,
                            'last_processed_unix': since_timestamp_unix,
                            'conversion_success': True
                        }
                        
                        # Utiliser le timestamp Unix pour les requêtes sur transactions
                        cursor.execute("""
                            SELECT COUNT(DISTINCT token_mint) FROM transactions 
                            WHERE created_at > ? AND token_mint IS NOT NULL AND token_mint != ''
                        """, (since_timestamp_unix,))
                        distinct_tokens_since = cursor.fetchone()[0]
                        
                        diagnosis['distinct_tokens_since_last'] = distinct_tokens_since
                        
                    except Exception as e:
                        diagnosis['timestamp_conversion'] = {
                            'error': str(e),
                            'conversion_success': False
                        }
                        
                        # Fallback: utiliser les dernières 24h
                        cursor.execute("""
                            SELECT COUNT(DISTINCT token_mint) FROM transactions 
                            WHERE created_at > (strftime('%s', 'now') - 86400) 
                            AND token_mint IS NOT NULL AND token_mint != ''
                        """)
                        distinct_tokens_since = cursor.fetchone()[0]
                        diagnosis['distinct_tokens_since_last'] = distinct_tokens_since
                else:
                    # Pas de timestamp de référence, utiliser les dernières 24h
                    cursor.execute("""
                        SELECT COUNT(DISTINCT token_mint) FROM transactions 
                        WHERE created_at > (strftime('%s', 'now') - 86400) 
                        AND token_mint IS NOT NULL AND token_mint != ''
                    """)
                    distinct_tokens_since = cursor.fetchone()[0]
                    diagnosis['distinct_tokens_since_last'] = distinct_tokens_since
                    diagnosis['timestamp_conversion'] = {
                        'note': 'No last_processed_created_at, using last 24h',
                        'conversion_success': True
                    }
                
                # 4. Vérifier quelques exemples de token_mint récents
                if self.last_processed_created_at:
                    try:
                        dt = datetime.fromisoformat(self.last_processed_created_at.replace('Z', ''))
                        since_timestamp_unix = int(dt.timestamp())
                        
                        cursor.execute("""
                            SELECT DISTINCT token_mint, MAX(created_at) as latest_created_at
                            FROM transactions 
                            WHERE created_at > ? AND token_mint IS NOT NULL AND token_mint != ''
                            GROUP BY token_mint
                            ORDER BY latest_created_at DESC
                            LIMIT 5
                        """, (since_timestamp_unix,))
                    except:
                        # Fallback si conversion échoue
                        cursor.execute("""
                            SELECT DISTINCT token_mint, MAX(created_at) as latest_created_at
                            FROM transactions 
                            WHERE created_at > (strftime('%s', 'now') - 86400) 
                            AND token_mint IS NOT NULL AND token_mint != ''
                            GROUP BY token_mint
                            ORDER BY latest_created_at DESC
                            LIMIT 5
                        """)
                else:
                    cursor.execute("""
                        SELECT DISTINCT token_mint, MAX(created_at) as latest_created_at
                        FROM transactions 
                        WHERE created_at > (strftime('%s', 'now') - 86400) 
                        AND token_mint IS NOT NULL AND token_mint != ''
                        GROUP BY token_mint
                        ORDER BY latest_created_at DESC
                        LIMIT 5
                    """)
                
                recent_token_examples = cursor.fetchall()
                diagnosis['recent_token_examples'] = []
                
                for row in recent_token_examples:
                    token_mint = row[0]
                    latest_created_at_unix = row[1]
                    
                    # Convertir en date lisible
                    try:
                        latest_created_at_readable = datetime.fromtimestamp(latest_created_at_unix).isoformat()
                    except:
                        latest_created_at_readable = "Error converting"
                    
                    example_data = {
                        'token_mint': token_mint,
                        'latest_created_at_unix': latest_created_at_unix,
                        'latest_created_at_readable': latest_created_at_readable
                    }
                    
                    # Vérifier si ce token existe déjà dans la table tokens
                    cursor.execute("""
                        SELECT address, no_data_available, failed_attempts, created_at as token_created_at
                        FROM tokens WHERE address = ?
                    """, (token_mint,))
                    
                    existing_token = cursor.fetchone()
                    if existing_token:
                        example_data['exists_in_tokens'] = True
                        example_data['no_data_available'] = existing_token[1]
                        example_data['failed_attempts'] = existing_token[2]
                        example_data['token_created_at'] = existing_token[3]
                    else:
                        example_data['exists_in_tokens'] = False
                    
                    # Vérifier si ce token est dans la queue
                    cursor.execute("""
                        SELECT status, created_at as queue_created_at FROM token_processing_queue 
                        WHERE token_address = ?
                    """, (token_mint,))
                    
                    queue_entry = cursor.fetchone()
                    if queue_entry:
                        example_data['in_queue'] = True
                        example_data['queue_status'] = queue_entry[0]
                        example_data['queue_created_at'] = queue_entry[1]
                    else:
                        example_data['in_queue'] = False
                    
                    diagnosis['recent_token_examples'].append(example_data)
                
                # 5. État de l'initialisation
                diagnosis['service_state'] = {
                    'initial_population_done': self.initial_population_done,
                    'last_processed_created_at': self.last_processed_created_at,
                    'cycle_count': self.cycle_count,
                    'running': self.running
                }
                
                # 6. Configuration
                diagnosis['config'] = {
                    'batch_size_new_tokens': self.config.processing.batch_size_new_tokens,
                    'initial_population_limit': getattr(self.config.processing, 'initial_population_limit', 1000),
                    'max_failed_attempts': self.config.processing.max_failed_attempts,
                    'retry_failed_after_hours': getattr(self.config.processing, 'retry_failed_after_hours', 168)
                }
                
                # 7. Statistiques des tokens existants
                cursor.execute("SELECT COUNT(*) FROM tokens")
                total_tokens = cursor.fetchone()[0]
                
                cursor.execute("SELECT COUNT(*) FROM tokens WHERE no_data_available = 1")
                flagged_tokens = cursor.fetchone()[0]
                
                cursor.execute("SELECT COUNT(*) FROM tokens WHERE failed_attempts > 0")
                failed_tokens = cursor.fetchone()[0]
                
                diagnosis['tokens_statistics'] = {
                    'total_tokens': total_tokens,
                    'flagged_no_data': flagged_tokens,
                    'with_failed_attempts': failed_tokens
                }
                
                # 8. Test de la requête get_new_tokens_since_timestamp
                if self.last_processed_created_at:
                    try:
                        self.logger.info("🔍 DIAGNOSTIC: Testing get_new_tokens_since_timestamp...")
                        
                        test_tokens, test_most_recent = self.token_repo.get_new_tokens_since_timestamp(
                            since_created_at=self.last_processed_created_at,
                            limit=5  # Petit test
                        )
                        
                        diagnosis['get_new_tokens_test'] = {
                            'success': True,
                            'tokens_found': len(test_tokens),
                            'most_recent_returned': test_most_recent,
                            'sample_tokens': list(test_tokens)[:3] if test_tokens else []
                        }
                        
                    except Exception as e:
                        diagnosis['get_new_tokens_test'] = {
                            'success': False,
                            'error': str(e)
                        }
                
                # 9. Analyse des filtres appliqués
                if self.last_processed_created_at:
                    try:
                        dt = datetime.fromisoformat(self.last_processed_created_at.replace('Z', ''))
                        since_timestamp_unix = int(dt.timestamp())
                        
                        # Tokens dans transactions mais exclus par les filtres
                        cursor.execute("""
                            SELECT COUNT(DISTINCT t.token_mint) 
                            FROM transactions t
                            WHERE t.created_at > ? 
                            AND t.token_mint IS NOT NULL 
                            AND t.token_mint != ''
                            AND t.token_mint IN (
                                SELECT address FROM tokens 
                                WHERE no_data_available = 1 
                                AND (no_data_last_check > datetime('now', '-7 days') OR failed_attempts >= 2)
                            )
                        """, (since_timestamp_unix,))
                        
                        filtered_out_count = cursor.fetchone()[0]
                        
                        diagnosis['filtering_analysis'] = {
                            'tokens_filtered_out_by_no_data_flag': filtered_out_count
                        }
                        
                    except Exception as e:
                        diagnosis['filtering_analysis'] = {
                            'error': str(e)
                        }
                
            return diagnosis
            
        except Exception as e:
            self.logger.error(f"Error in token discovery diagnosis: {e}", exc_info=True)
            return {'error': str(e), 'timestamp': datetime.now().isoformat()}

    def _add_tokens_since_last_timestamp(self) -> int:
        """Ajouter les tokens depuis le dernier timestamp traité - VERSION CORRIGÉE"""
        try:
            if not self.last_processed_created_at:
                self.logger.warning("🔍 DEBUG: No last processed created_at, skipping new tokens search")
                return 0
            
            self.logger.info(f"🔍 DEBUG: Searching for new tokens since last_processed_created_at='{self.last_processed_created_at}' (datetime format)")
            
            # CORRECTION: Convertir le format datetime en timestamp Unix pour les requêtes sur transactions
            try:
                dt = datetime.fromisoformat(self.last_processed_created_at.replace('Z', ''))
                last_timestamp_unix = int(dt.timestamp())
                self.logger.info(f"🔍 DEBUG: Converted to unix timestamp: {last_timestamp_unix}")
            except Exception as e:
                self.logger.error(f"Error converting datetime to unix: {e}")
                return 0
                
            # Vérifier d'abord s'il y a des nouvelles transactions dans la table
            with self.db_connection.get_connection_context() as conn:
                cursor = conn.cursor()
                
                # CORRECTION: Utiliser le timestamp Unix pour les requêtes sur transactions
                cursor.execute("""
                    SELECT COUNT(*) FROM transactions 
                    WHERE created_at > ?
                """, (last_timestamp_unix,))  # Unix timestamp au lieu de datetime string
                
                new_transactions_count = cursor.fetchone()[0]
                self.logger.info(f"🔍 DEBUG: Found {new_transactions_count} transactions since unix timestamp {last_timestamp_unix}")
                
                # Compter les tokens mint distincts dans ces nouvelles transactions
                cursor.execute("""
                    SELECT COUNT(DISTINCT token_mint) FROM transactions 
                    WHERE created_at > ? AND token_mint IS NOT NULL AND token_mint != ''
                """, (last_timestamp_unix,))
                
                distinct_tokens_in_new_transactions = cursor.fetchone()[0]
                self.logger.info(f"🔍 DEBUG: Found {distinct_tokens_in_new_transactions} distinct token_mint in new transactions")
                
                # AJOUT: Voir quelques exemples de tokens dans les nouvelles transactions
                if distinct_tokens_in_new_transactions > 0:
                    cursor.execute("""
                        SELECT DISTINCT token_mint, created_at, datetime(created_at, 'unixepoch') as readable_date
                        FROM transactions 
                        WHERE created_at > ? AND token_mint IS NOT NULL AND token_mint != ''
                        ORDER BY created_at DESC LIMIT 3
                    """, (last_timestamp_unix,))
                    
                    examples = cursor.fetchall()
                    self.logger.info("🔍 DEBUG: Examples of tokens in new transactions:")
                    for ex in examples:
                        self.logger.info(f"  Token: {ex[0][:8]}..., Unix: {ex[1]}, Date: {ex[2]}")
                
                # Vérifier combien de ces tokens existent déjà dans la table tokens
                cursor.execute("""
                    SELECT COUNT(DISTINCT t.token_mint) FROM transactions t
                    INNER JOIN tokens tk ON t.token_mint = tk.address
                    WHERE t.created_at > ? AND t.token_mint IS NOT NULL AND t.token_mint != ''
                """, (last_timestamp_unix,))
                
                existing_tokens_count = cursor.fetchone()[0]
                self.logger.info(f"🔍 DEBUG: {existing_tokens_count} of these tokens already exist in tokens table")
                
                # Calculer combien de tokens sont réellement nouveaux
                potentially_new_tokens = distinct_tokens_in_new_transactions - existing_tokens_count
                self.logger.info(f"🔍 DEBUG: {potentially_new_tokens} tokens are potentially new")
            
            # Chercher les nouveaux tokens depuis le dernier timestamp
            # NOTE: get_new_tokens_since_timestamp fait la conversion datetime -> unix en interne
            token_addresses, most_recent_created_at = self.token_repo.get_new_tokens_since_timestamp(
                since_created_at=self.last_processed_created_at,  # Format datetime (sera converti en interne)
                limit=self.config.processing.batch_size_new_tokens
            )
            
            if token_addresses:
                self.logger.info(f"🔍 DEBUG: get_new_tokens_since_timestamp returned {len(token_addresses)} addresses")
                
                # Afficher quelques exemples d'adresses trouvées
                sample_addresses = list(token_addresses)[:3]
                for addr in sample_addresses:
                    self.logger.info(f"🔍 DEBUG: Example token address: {addr}")
                
                added_count = self.queue_repo.add_tokens_to_queue(
                    list(token_addresses),
                    source="new_transactions"
                )
                
                self.logger.info(f"🔍 DEBUG: Queue add_tokens_to_queue returned: {added_count}")
                
                # Mettre à jour le timestamp le plus récent
                if most_recent_created_at and most_recent_created_at > self.last_processed_created_at:
                    old_timestamp = self.last_processed_created_at
                    self.last_processed_created_at = most_recent_created_at
                    
                    self.logger.info(f"📥 New tokens: {added_count} added to queue")
                    self.logger.info(f"📅 Updated last_processed_created_at: {old_timestamp} → {most_recent_created_at}")
                else:
                    self.logger.warning(f"🔍 DEBUG: most_recent_created_at ({most_recent_created_at}) not newer than last_processed ({self.last_processed_created_at})")
                
                return added_count
            else:
                self.logger.info("🔍 DEBUG: get_new_tokens_since_timestamp returned no addresses")
                
                # AJOUT: Debug supplémentaire si aucun token n'est trouvé
                if potentially_new_tokens > 0:
                    self.logger.warning(f"🔍 DEBUG: Expected {potentially_new_tokens} new tokens but get_new_tokens_since_timestamp found 0")
                    self.logger.warning("🔍 DEBUG: This might indicate a filtering issue in get_new_tokens_since_timestamp")
                
                return 0
                
        except Exception as e:
            self.logger.error(f"Error adding tokens since last timestamp: {e}", exc_info=True)
            return 0

    def _update_existing_prices(self) -> int:
        """Update existing token prices"""
        self.logger.debug("🔄 Updating existing token prices...")
        
        # Use the centralized configuration from processing
        price_update_limit = self.config.processing.batch_size_price_updates
        price_update_interval = self.config.processing.price_update_interval_seconds
        max_failed_attempts = self.config.processing.max_failed_attempts
        
        # Get tokens needing updates
        tokens_to_update = self.token_repo.get_tokens_needing_price_update(
            interval_seconds=price_update_interval,
            max_failed_attempts=max_failed_attempts,
            limit=price_update_limit
        )
        
        if not tokens_to_update:
            self.logger.debug("No tokens need price updates")
            return 0
        
        self.logger.info(f"📊 Updating {len(tokens_to_update)} token prices")
        
        # Process updates in batch
        return asyncio.run(self.batch_processor.process_price_updates(tokens_to_update))
    
    def _run_historization_improved(self) -> int:
        """Run token historization with better logic"""
        try:
            # CORRECTION: Fix configuration attribute access for historization
            # Use processing.historization_interval_seconds which exists in the config
            historization_interval = getattr(
                self.config.processing, 
                'historization_interval_seconds', 
                3600  # Default 1 heure
            )
            
            # Obtenir les tokens qui ont besoin d'historisation
            tokens_to_historize = self.token_repo.get_tokens_needing_historization(
                interval_seconds=historization_interval,
                limit=min(50, self.config.processing.batch_size_historization)
            )
            
            if not tokens_to_historize:
                self.logger.debug("📈 No tokens need historization")
                return 0
            
            self.logger.info(f"📈 Starting historization for {len(tokens_to_historize)} tokens")
            
            # Utiliser le processeur d'historisation si disponible
            if self.historization_processor:
                try:
                    result = self.historization_processor.manually_historize_tokens(tokens_to_historize)
                    successful_count = result.get('successful', 0)
                    self.logger.info(f"📈 Historization completed: {successful_count}/{len(tokens_to_historize)} successful")
                    return successful_count
                except Exception as e:
                    self.logger.error(f"Error using historization processor: {e}")
                    # Fallback vers la méthode directe
            
            # Fallback vers l'historisation directe
            successful_count = 0
            for token_address in tokens_to_historize:
                try:
                    if self.history_repo.create_snapshot(token_address):
                        successful_count += 1
                except Exception as e:
                    self.logger.debug(f"Error historizing {token_address[:8]}...: {e}")
                    continue
            
            self.logger.info(f"📈 Historization completed: {successful_count}/{len(tokens_to_historize)} successful")
            return successful_count
                
        except Exception as e:
            self.logger.error(f"Error in historization: {e}")
            return 0
    
    def _run_periodic_tasks(self):
        """Run periodic maintenance tasks"""
        # Tâches périodiques moins fréquentes pour éviter la surcharge
        
        # Every 5 cycles - update creation timestamps
        if self.cycle_count % 5 == 0:
            self._update_creation_timestamps()
        
        # Every 10 cycles - database maintenance
        if self.cycle_count % 10 == 0:
            self._database_maintenance()
    
    def _update_creation_timestamps(self):
        """Update missing creation timestamps"""
        self.logger.debug("⏰ Updating creation timestamps...")
        
        try:
            tokens_missing_timestamps = self.token_repo.get_tokens_missing_creation_timestamp(
                limit=min(50, self.config.apis.dexscreener_batch_size)
            )
            
            if not tokens_missing_timestamps:
                self.logger.debug("No tokens need timestamp updates")
                return
            
            updated_count = 0
            for token_address in tokens_missing_timestamps:
                try:
                    timestamp = self.dex_client.get_token_creation_timestamp(token_address)
                    if timestamp:
                        if self.token_repo.update_creation_timestamp(token_address, timestamp):
                            updated_count += 1
                    
                    # CORRECTION: Fix rate limiting delay access
                    rate_limit_delay = getattr(self.config.processing, 'rate_limit_delay', 0.2)
                    time.sleep(rate_limit_delay)
                    
                except Exception as e:
                    self.logger.error(f"Error updating timestamp for {token_address}: {e}")
                    continue
            
            if updated_count > 0:
                self.logger.info(f"⏰ Updated {updated_count} creation timestamps")
                self.cycle_logger.record_operation('creation_timestamps', updated_count)
                
        except Exception as e:
            self.logger.error(f"Error in update_creation_timestamps: {e}")
    
    def _database_maintenance(self):
        """Perform database maintenance"""
        self.logger.debug("🧹 Running database maintenance...")
        
        try:
            # Check database health
            if not self.db_connection.check_health():
                self.logger.warning("Database health check failed during maintenance")
            
            # Get flagged tokens stats
            stats = self.token_repo.get_flagged_tokens_stats()
            if stats:
                self.logger.info(f"📊 Flagged tokens: {stats}")
            
            # Periodic vacuum (every 100 cycles)
            if self.cycle_count % 100 == 0:
                self.logger.info("🧹 Running database vacuum...")
                self.db_connection.vacuum_database()
                
        except Exception as e:
            self.logger.error(f"Error in database maintenance: {e}")
    
    def _start_sync_cycle(self) -> int:
        """Start a new sync cycle"""
        cycle_id = int(time.time() * 1000)
        
        # Éviter la duplication d'ID
        while cycle_id == self.current_sync_cycle_id:
            time.sleep(0.001)  # Attendre 1ms
            cycle_id = int(time.time() * 1000)
        
        self.current_sync_cycle_id = cycle_id
        
        self.api_tracker.set_current_cycle(cycle_id)
        self.cycle_logger.start_cycle(cycle_id)
        
        return cycle_id
    
    def _end_sync_cycle(self, cycle_id: int):
        """End the current sync cycle with detailed API stats"""
        cycle_summary = self.cycle_logger.get_cycle_api_summary()
        
        # Log detailed API breakdown
        self.logger.info("🌐 API CALLS BREAKDOWN:")
        self.logger.info(f"  📡 Total API calls: {sum(cycle_summary['calls_by_client'].values())}")
        
        # By client
        for client, calls in cycle_summary['calls_by_client'].items():
            self.logger.info(f"  🔸 {client}: {calls} calls total")
            
            # Batch vs individual breakdown
            if client in cycle_summary['batch_vs_individual']:
                batch_count = cycle_summary['batch_vs_individual'][client]['batch']
                individual_count = cycle_summary['batch_vs_individual'][client]['individual']
                self.logger.info(f"     └─ Batch calls: {batch_count}, Individual calls: {individual_count}")
        
        # Individual calls summary
        if cycle_summary['total_individual_calls'] > 0:
            self.logger.info(f"  ⚠️ Total individual calls: {cycle_summary['total_individual_calls']}")
            self.logger.info(f"  ⚠️ Individual addresses: {cycle_summary['individual_addresses_count']}")
        
        self.cycle_logger.end_cycle()
        self.api_tracker.end_cycle()
    
    def _wait_for_next_cycle(self):
        """Wait for the next sync cycle in a way that can be interrupted."""
        interval = self.config.processing.enrichment_interval_seconds
        self.logger.debug(f"⏳ Waiting {interval} seconds until next cycle...")

        # Print statistics periodically
        if self.cycle_count % 5 == 0:
            self._print_statistics()

        end_time = time.time() + interval
        while time.time() < end_time:
            if not self.running:
                break
            time.sleep(1)  # Sleep for 1 second at a time
    
    def _print_statistics(self):
        """Print current service statistics"""
        try:
            if self.stats['start_time']:
                runtime = time.time() - self.stats['start_time']
                runtime_str = str(timedelta(seconds=int(runtime)))
            else:
                runtime_str = "N/A"
            
            self.logger.info("=== 📊 SYNC SERVICE STATISTICS ===")
            self.logger.info(f"⏱️ Runtime: {runtime_str}")
            self.logger.info(f"🔄 Cycles completed: {self.stats['cycles_completed']}")
            self.logger.info(f"📊 Tokens processed: {self.stats['processed_tokens']}")
            self.logger.info(f"✅ Successful updates: {self.stats['successful_updates']}")
            self.logger.info(f"❌ Failed updates: {self.stats['failed_updates']}")
            
            if self.stats['processed_tokens'] > 0:
                success_rate = (self.stats['successful_updates'] / self.stats['processed_tokens']) * 100
                self.logger.info(f"📈 Success rate: {success_rate:.1f}%")
            
            # API statistics
            self._print_api_statistics()
            
            # Queue statistics
            queue_stats = self.queue_repo.get_queue_status_summary()
            if queue_stats:
                self.logger.info("=== 📋 QUEUE STATISTICS ===")
                for key, value in queue_stats.items():
                    if key in ['pending', 'processing', 'completed', 'failed']:
                        self.logger.info(f"  {key}: {value}")
                    elif key == 'completion_rate_percent':
                        self.logger.info(f"  completion_rate: {value}%")
                    elif key == 'avg_processing_time_seconds':
                        self.logger.info(f"  avg_processing_time: {value:.1f}s")
        
        except Exception as e:
            self.logger.error(f"Error printing statistics: {e}")
    
    def _print_api_statistics(self):
        """Print API usage statistics"""
        try:
            self.logger.info("=== 🌐 API STATISTICS ===")
            
            # Stats globales
            global_stats = self.api_tracker.get_global_stats()
            if global_stats:
                self.logger.info(f"🌍 Global: {global_stats.get('total_api_calls', 0)} total calls")
                self.logger.info(f"📊 Success rate: {global_stats.get('global_success_rate', 0):.1f}%")
                self.logger.info(f"⚡ Current rate: {global_stats.get('current_rate_1m', 0)} calls/min")
            
            # Top APIs par nombre d'appels
            top_apis = self.api_tracker.get_top_apis(limit=5, sort_by='calls')
            if top_apis:
                self.logger.debug("🔝 Top APIs by calls:")
                for api_name, stats in top_apis:
                    self.logger.debug(
                        f"  🔗 {api_name}: {stats.get('total_calls', 0)} calls, "
                        f"avg {stats.get('avg_duration_seconds', 0):.3f}s, "
                        f"success {stats.get('success_rate', 0):.1f}%"
                    )
            
            # Health report
            health_report = self.api_tracker.get_api_health_report()
            if health_report.get('failing_apis'):
                self.logger.warning(f"⚠️ Failing APIs: {health_report['failing_apis']}")
            if health_report.get('degraded_apis'):
                self.logger.warning(f"🐌 Degraded APIs: {health_report['degraded_apis']}")
                
        except Exception as e:
            self.logger.debug(f"Error printing API statistics: {e}")
    
    def add_tokens_to_queue(self, token_addresses: list) -> int:
        """
        Add tokens to the processing queue
        
        Args:
            token_addresses: List of token addresses to add
            
        Returns:
            Number of tokens added to queue
        """
        if not token_addresses:
            return 0
        
        try:
            return self.queue_repo.add_tokens_to_queue(token_addresses)
        except Exception as e:
            self.logger.error(f"Error adding tokens to queue: {e}")
            return 0
    
    def get_service_status(self) -> Dict[str, Any]:
        """Get current service status"""
        try:
            return {
                'running': self.running,
                'current_cycle_id': self.current_sync_cycle_id,
                'cycle_count': self.cycle_count,
                'stats': self.stats.copy(),
                'queue_stats': self.queue_repo.get_queue_status_summary(),
                'api_stats': self.api_tracker.get_stats() if hasattr(self.api_tracker, 'get_stats') else {},
                'database_healthy': self.db_connection.check_health(),
                'historization_processor_available': self.historization_processor is not None
            }
        except Exception as e:
            self.logger.error(f"Error getting service status: {e}")
            return {
                'running': self.running,
                'error': str(e)
            }
    
    def force_historization(self, token_addresses: Optional[list] = None) -> Dict[str, Any]:
        """
        Force historization for specific tokens or all eligible tokens
        
        Args:
            token_addresses: Optional list of specific token addresses
            
        Returns:
            Historization results
        """
        try:
            if token_addresses:
                # Force historization for specific tokens
                if self.historization_processor:
                    result = self.historization_processor.manually_historize_tokens(token_addresses)
                else:
                    successful_count = 0
                    for token_address in token_addresses:
                        try:
                            if self.history_repo.create_snapshot(token_address):
                                successful_count += 1
                        except Exception as e:
                            self.logger.error(f"Error historizing {token_address}: {e}")
                    
                    result = {
                        'success': True,
                        'processed': len(token_addresses),
                        'successful': successful_count,
                        'failed': len(token_addresses) - successful_count
                    }
            else:
                # Force historization for all eligible tokens
                result = {'successful': self._run_historization_improved()}
            
            return result
            
        except Exception as e:
            self.logger.error(f"Error in force historization: {e}")
            return {'success': False, 'error': str(e)}
    
    def cleanup_old_data(self, days_to_keep: int = 30) -> Dict[str, Any]:
        """
        Clean up old historical data
        
        Args:
            days_to_keep: Number of days of data to keep
            
        Returns:
            Cleanup results
        """
        try:
            deleted_count = self.history_repo.cleanup_old_history(days_to_keep)
            
            return {
                'success': True,
                'records_deleted': deleted_count,
                'days_kept': days_to_keep
            }
            
        except Exception as e:
            self.logger.error(f"Error cleaning up old data: {e}")
            return {'success': False, 'error': str(e)}
    
    def stop(self):
        """Stop the synchronization service"""
        self.logger.info("🛑 Stopping Token Sync Service...")
        self.running = False
        
        try:
            # Stop historization processor if available
            if self.historization_processor and hasattr(self.historization_processor, 'stop_processor'):
                self.historization_processor.stop_processor()
            
            # Close API clients
            self.dex_client.close()
            
            # Print final statistics
            self._print_statistics()
            
            self.logger.info("✅ Token Sync Service stopped successfully")
            
        except Exception as e:
            self.logger.error(f"Error during service shutdown: {e}")


def create_sync_service(config, logger: Optional[logging.Logger] = None) -> SyncService:
    """
    Factory function to create a configured sync service
    
    Args:
        config: Configuration object
        logger: Optional logger instance
        
    Returns:
        Configured SyncService instance
    """
    return SyncService(config=config, logger=logger)