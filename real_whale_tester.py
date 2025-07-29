#!/usr/bin/env python3
"""
🐋 REAL Whale Detection Tester - VERSION CORRIGÉE
Teste si le système détecte VRAIMENT les whales en temps réel
"""

import asyncio
import logging
import sqlite3
import time
from datetime import datetime, timedelta
from typing import Dict, List
import aiohttp
from solana.rpc.async_api import AsyncClient
from solders.signature import Signature

# Configuration logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('real_whale_test.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger('real_whale_tester')

class RealWhaleDetectionTester:
    """Testeur de détection whale RÉELLE - VERSION CORRIGÉE"""
    
    def __init__(self):
        self.database_path = "tokens.db"
        self.session = None
        self.client = None
        self.running = False
        
        # Compteurs
        self.stats = {
            'signatures_tested': 0,
            'real_whales_found': 0,
            'api_calls_made': 0,
            'parsing_errors': 0,
            'start_time': datetime.now()
        }
    
    async def start_real_testing(self):
        """Démarrer le test de détection RÉELLE"""
        logger.info("🚀 === TEST DÉTECTION WHALE RÉELLE (VERSION CORRIGÉE) ===")
        logger.info("Ce script va tester si votre système détecte de VRAIES whales")
        
        self.session = aiohttp.ClientSession()
        self.client = AsyncClient("https://rpc.helius.xyz/?api-key=872ddf73-4cfd-4263-a418-521bbde27eb8")
        self.running = True
        
        try:
            # Import du système whale
            from whale_detector_integration import (
                whale_detector, 
                start_whale_monitoring,
                process_websocket_logs_for_whales,
                WHALE_THRESHOLD_USD,
                CRITICAL_THRESHOLD_USD
            )
            
            logger.info(f"💰 Seuils configurés: Whale=${WHALE_THRESHOLD_USD} | Critique=${CRITICAL_THRESHOLD_USD}")
            
            # Démarrer le système
            await start_whale_monitoring()
            logger.info("✅ Système whale démarré")
            
            # Lancer les tests en parallèle
            await asyncio.gather(
                self.test_recent_large_transactions(),
                self.monitor_database_changes(),
                self.display_real_stats()
            )
            
        except Exception as e:
            logger.error(f"❌ Erreur: {e}")
        finally:
            await self.cleanup()
    
    async def test_recent_large_transactions(self):
        """Tester avec de vraies signatures récentes - VERSION CORRIGÉE"""
        logger.info("🔍 Test avec vraies signatures - VERSION CORRIGÉE...")
        
        # Vos signatures trouvées sur Solscan
        known_large_signatures = [
            '3bGKecHJKP13B47p1WHyVMuSqEJ3QCqBKkgnuX2oBQPXUiSJc2ibLbu9PSR6CUxoiQNDSHUTsBEHfwiCidai7xMj',
            # Ajoutez d'autres signatures ici
        ]
        
        if not known_large_signatures:
            logger.warning("⚠️ Pas de signatures test")
            return
        
        for signature in known_large_signatures:
            if not self.running:
                break
                
            try:
                logger.info(f"🧪 Test signature: {signature[:20]}...")
                
                # Récupérer la transaction réelle avec la bonne méthode
                sig = Signature.from_string(signature)
                tx = await self.client.get_transaction(
                    sig,
                    commitment="finalized",
                    max_supported_transaction_version=0
                )
                
                if tx.value:
                    # CORRECTION: Accès correct aux logs selon la structure API
                    logs = []
                    
                    # Méthode 1: Transaction standard
                    if hasattr(tx.value, 'transaction') and tx.value.transaction:
                        if hasattr(tx.value.transaction, 'meta') and tx.value.transaction.meta:
                            logs = tx.value.transaction.meta.log_messages or []
                        elif hasattr(tx.value, 'meta') and tx.value.meta:
                            logs = tx.value.meta.log_messages or []
                    
                    # Méthode 2: Accès direct aux meta
                    elif hasattr(tx.value, 'meta') and tx.value.meta:
                        logs = tx.value.meta.log_messages or []
                    
                    # Méthode 3: Vérifier les attributs disponibles
                    else:
                        logger.info(f"🔍 Attributs disponibles: {dir(tx.value)}")
                        if hasattr(tx.value, 'log_messages'):
                            logs = tx.value.log_messages or []
                    
                    if logs:
                        logger.info(f"📋 {len(logs)} logs trouvés")
                        
                        # Afficher quelques logs pour debug
                        for i, log in enumerate(logs[:3]):
                            logger.info(f"   Log {i}: {log[:80]}...")
                        
                        # Compter les whales avant le test
                        whales_before = self.count_whale_transactions()
                        
                        # Traiter avec le système whale
                        from whale_detector_integration import process_websocket_logs_for_whales
                        await process_websocket_logs_for_whales(signature, logs)
                        
                        # Vérifier si une whale a été détectée
                        await asyncio.sleep(3)  # Laisser le temps au processing
                        whales_after = self.count_whale_transactions()
                        
                        if whales_after > whales_before:
                            logger.info(f"✅ SUCCÈS: Whale détectée pour {signature[:20]}...")
                            self.stats['real_whales_found'] += 1
                        else:
                            logger.info(f"❌ Aucune whale détectée pour {signature[:20]}...")
                            
                            # Debug: vérifier pourquoi pas détectée
                            await self.debug_why_not_detected(signature, logs)
                        
                        self.stats['signatures_tested'] += 1
                        
                    else:
                        logger.warning(f"⚠️ Aucun log trouvé pour {signature[:20]}...")
                        # Debug: afficher la structure de la transaction
                        await self.debug_transaction_structure(tx.value)
                    
                else:
                    logger.warning(f"⚠️ Transaction non trouvée: {signature[:20]}...")
                
                await asyncio.sleep(5)  # Éviter le rate limiting
                
            except Exception as e:
                logger.error(f"❌ Erreur test signature {signature[:20]}...: {e}")
                self.stats['parsing_errors'] += 1
                
                # Debug l'erreur
                import traceback
                logger.debug(f"Stack trace: {traceback.format_exc()}")
    
    async def debug_transaction_structure(self, tx_value):
        """Debug: afficher la structure de la transaction"""
        logger.info("🔍 DEBUG: Structure de la transaction:")
        logger.info(f"   Type: {type(tx_value)}")
        logger.info(f"   Attributs: {[attr for attr in dir(tx_value) if not attr.startswith('_')]}")
        
        if hasattr(tx_value, 'transaction'):
            logger.info(f"   transaction.type: {type(tx_value.transaction)}")
            if hasattr(tx_value.transaction, 'meta'):
                logger.info(f"   transaction.meta exists: {tx_value.transaction.meta is not None}")
        
        if hasattr(tx_value, 'meta'):
            logger.info(f"   meta exists: {tx_value.meta is not None}")
            if tx_value.meta:
                logger.info(f"   meta.type: {type(tx_value.meta)}")
                logger.info(f"   meta.attributes: {[attr for attr in dir(tx_value.meta) if not attr.startswith('_')]}")
    
    async def debug_why_not_detected(self, signature: str, logs: List[str]):
        """Debug: pourquoi la whale n'a pas été détectée"""
        logger.info(f"🔍 DEBUG: Analyse pourquoi {signature[:20]}... pas détectée:")
        
        # Vérifier les indicateurs de swap
        swap_indicators = []
        for log in logs:
            log_lower = log.lower()
            if any(keyword in log_lower for keyword in ['jupiter', 'swap', 'route', 'raydium', 'pump']):
                swap_indicators.append(log[:100])
        
        if swap_indicators:
            logger.info(f"   ✅ Indicateurs swap trouvés: {len(swap_indicators)}")
            for indicator in swap_indicators[:3]:
                logger.info(f"      {indicator}")
        else:
            logger.warning(f"   ❌ Aucun indicateur de swap trouvé")
            logger.info(f"   Premiers logs: {logs[:3]}")
        
        # Vérifier les programmes impliqués
        program_logs = [log for log in logs if 'Program' in log and 'invoke' in log]
        logger.info(f"   Programmes invoqués: {len(program_logs)}")
        for prog_log in program_logs[:3]:
            logger.info(f"      {prog_log}")
    
    async def monitor_database_changes(self):
        """Surveiller les changements dans la base de données"""
        logger.info("💾 Surveillance des changements base de données...")
        
        last_count = self.count_whale_transactions()
        logger.info(f"📊 Transactions whale initiales: {last_count}")
        
        while self.running:
            try:
                current_count = self.count_whale_transactions()
                
                if current_count > last_count:
                    new_whales = current_count - last_count
                    logger.info(f"🆕 {new_whales} nouvelle(s) transaction(s) whale détectée(s)!")
                    
                    # Récupérer les détails des nouvelles whales
                    new_whale_details = self.get_recent_whale_details(limit=new_whales)
                    
                    for whale in new_whale_details:
                        amount = whale.get('amount_usd', 0)
                        tx_type = whale.get('transaction_type', 'unknown')
                        dex = whale.get('dex_id', 'unknown')
                        timestamp = whale.get('timestamp', 'unknown')
                        
                        logger.info(f"🐋 NOUVELLE WHALE: ${amount:,.0f} {tx_type} sur {dex} à {timestamp}")
                    
                    last_count = current_count
                
                await asyncio.sleep(10)  # Check toutes les 10 secondes
                
            except Exception as e:
                logger.error(f"❌ Erreur monitoring DB: {e}")
                await asyncio.sleep(30)
    
    def count_whale_transactions(self) -> int:
        """Compter le nombre total de transactions whale"""
        conn = sqlite3.connect(self.database_path)
        cursor = conn.cursor()
        
        try:
            cursor.execute("SELECT COUNT(*) FROM whale_transactions_live")
            return cursor.fetchone()[0]
        except:
            return 0
        finally:
            conn.close()
    
    def get_recent_whale_details(self, limit: int = 5) -> List[Dict]:
        """Récupérer les détails des whales récentes"""
        conn = sqlite3.connect(self.database_path)
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                SELECT * FROM whale_transactions_live 
                ORDER BY created_at DESC 
                LIMIT ?
            ''', (limit,))
            
            columns = [desc[0] for desc in cursor.description]
            results = []
            
            for row in cursor.fetchall():
                results.append(dict(zip(columns, row)))
            
            return results
        except:
            return []
        finally:
            conn.close()
    
    async def display_real_stats(self):
        """Afficher les statistiques des tests réels"""
        while self.running:
            try:
                uptime = datetime.now() - self.stats['start_time']
                total_whales = self.count_whale_transactions()
                
                logger.info("📊 === STATS DÉTECTION RÉELLE ===")
                logger.info(f"   ⏱️  Uptime: {uptime}")
                logger.info(f"   🔍 Signatures testées: {self.stats['signatures_tested']}")
                logger.info(f"   🐋 Whales réelles trouvées: {self.stats['real_whales_found']}")
                logger.info(f"   💾 Total whales en DB: {total_whales}")
                logger.info(f"   ❌ Erreurs parsing: {self.stats['parsing_errors']}")
                
                if self.stats['signatures_tested'] > 0:
                    success_rate = (self.stats['real_whales_found'] / self.stats['signatures_tested']) * 100
                    logger.info(f"   📈 Taux de succès: {success_rate:.1f}%")
                
                logger.info("=" * 40)
                
                await asyncio.sleep(120)  # Stats toutes les 2 minutes
                
            except Exception as e:
                logger.error(f"❌ Erreur stats: {e}")
                await asyncio.sleep(180)
    
    async def cleanup(self):
        """Nettoyage des ressources"""
        self.running = False
        if self.session:
            await self.session.close()
        if self.client:
            await self.client.close()
        
        logger.info("🏁 === RÉSULTATS FINAUX ===")
        logger.info(f"   🔍 Signatures testées: {self.stats['signatures_tested']}")
        logger.info(f"   🐋 Whales détectées: {self.stats['real_whales_found']}")
        logger.info(f"   ❌ Erreurs: {self.stats['parsing_errors']}")
        
        if self.stats['signatures_tested'] > 0:
            success_rate = (self.stats['real_whales_found'] / self.stats['signatures_tested']) * 100
            logger.info(f"   📈 Taux de détection: {success_rate:.1f}%")
        
        logger.info("✅ Test terminé!")

async def main():
    """Point d'entrée principal"""
    print("🐋 === TESTEUR DÉTECTION WHALE RÉELLE (CORRIGÉ) ===")
    print("Ce script teste si votre système détecte de VRAIES whales")
    print("Ctrl+C pour arrêter\n")
    
    tester = RealWhaleDetectionTester()
    
    try:
        await tester.start_real_testing()
    except KeyboardInterrupt:
        logger.info("👋 Arrêt demandé")
        tester.running = False
    except Exception as e:
        logger.error(f"❌ Erreur fatale: {e}")

if __name__ == "__main__":
    asyncio.run(main())