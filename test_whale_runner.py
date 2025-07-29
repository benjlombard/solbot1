#!/usr/bin/env python3
"""
🐋 Whale Detection Test Runner - Script de test continu
Lance les tests whale en continu avec des logs détaillés
"""

import asyncio
import logging
import signal
import sqlite3
import time
from datetime import datetime, timedelta
from typing import Dict, List
import sys
import os

# Import du système whale
try:
    from whale_detector_integration import (
        whale_detector, 
        whale_api,
        start_whale_monitoring, 
        stop_whale_monitoring,
        process_websocket_logs_for_whales,
        WHALE_THRESHOLD_USD,
        CRITICAL_THRESHOLD_USD
    )
except ImportError as e:
    print(f"❌ Erreur import: {e}")
    print("💡 Assurez-vous que whale_detector_integration.py est dans le même dossier")
    sys.exit(1)

# Configuration des logs
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('whale_test_runner.log', encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger('whale_test_runner')

class WhaleTestRunner:
    """Runner de test continu pour la détection whale"""
    
    def __init__(self, database_path: str = "tokens.db"):
        self.database_path = database_path
        self.running = False
        self.stats = {
            'total_checks': 0,
            'whales_detected': 0,
            'api_calls': 0,
            'errors': 0,
            'start_time': None
        }
        
        # Gestionnaire de signal pour arrêt propre
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)
    
    def signal_handler(self, signum, frame):
        """Gestionnaire d'arrêt propre"""
        logger.info(f"🛑 Signal {signum} reçu, arrêt en cours...")
        self.running = False
    
    async def start_continuous_testing(self):
        """Lancer les tests en continu"""
        logger.info("🚀 === WHALE DETECTION TEST RUNNER === 🚀")
        logger.info(f"📊 Seuils: Whale=${WHALE_THRESHOLD_USD:,} | Critique=${CRITICAL_THRESHOLD_USD:,}")
        
        self.running = True
        self.stats['start_time'] = datetime.now()
        
        # Créer des données de test initiales
        await self.setup_test_data()
        
        # Démarrer le système whale
        try:
            await start_whale_monitoring()
            logger.info("✅ Whale monitoring system started")
        except Exception as e:
            logger.error(f"❌ Erreur démarrage whale monitoring: {e}")
            return
        
        # Lancer les tâches de test en parallèle
        tasks = [
            self.monitor_whale_activity(),
            self.test_api_endpoints(),
            self.simulate_websocket_logs(),
            self.display_stats(),
            self.check_system_health()
        ]
        
        try:
            await asyncio.gather(*tasks, return_exceptions=True)
        except Exception as e:
            logger.error(f"❌ Erreur dans les tâches: {e}")
        finally:
            await stop_whale_monitoring()
            self.display_final_stats()
    
    async def setup_test_data(self):
        """Créer des données whale de test"""
        logger.info("🔧 Setup des données de test...")
        
        conn = sqlite3.connect(self.database_path)
        cursor = conn.cursor()
        
        try:
            # Nettoyer les anciennes données de test
            cursor.execute("DELETE FROM whale_transactions_live WHERE wallet_label LIKE '%TEST%'")
            
            # Créer quelques transactions de test
            test_data = [
                {
                    'signature': f'test_signature_{int(time.time())}_{i}',
                    'token_address': 'So11111111111111111111111111111111111111112',
                    'wallet_address': f'test_wallet_{i}aBcDefGhIjKlMnOpQrStUvWxYz123',
                    'transaction_type': 'buy' if i % 2 == 0 else 'sell',
                    'amount_usd': 5000 + (i * 1000),
                    'amount_tokens': 1000000,
                    'timestamp': datetime.now() - timedelta(minutes=i*5),
                    'price_impact': 0.5,
                    'is_known_whale': i % 3 == 0,
                    'wallet_label': f'TEST Whale #{i}',
                    'is_in_database': True,
                    'dex_id': ['jupiter', 'raydium', 'pump_fun'][i % 3]
                }
                for i in range(10)
            ]
            
            for data in test_data:
                cursor.execute('''
                    INSERT OR REPLACE INTO whale_transactions_live (
                        signature, token_address, wallet_address, transaction_type,
                        amount_usd, amount_tokens, timestamp, price_impact,
                        is_known_whale, wallet_label, is_in_database, dex_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    data['signature'], data['token_address'], data['wallet_address'],
                    data['transaction_type'], data['amount_usd'], data['amount_tokens'],
                    data['timestamp'], data['price_impact'], data['is_known_whale'],
                    data['wallet_label'], data['is_in_database'], data['dex_id']
                ))
            
            conn.commit()
            logger.info(f"✅ Créé {len(test_data)} transactions whale de test")
            
        except Exception as e:
            logger.error(f"❌ Erreur setup données test: {e}")
            self.stats['errors'] += 1
        finally:
            conn.close()
    
    async def monitor_whale_activity(self):
        """Monitorer l'activité whale en continu"""
        logger.info("👀 Démarrage monitoring activité whale...")
        
        last_check = datetime.now()
        
        while self.running:
            try:
                # Vérifier les nouvelles transactions
                new_whales = self.get_new_whale_transactions(last_check)
                
                if new_whales:
                    self.stats['whales_detected'] += len(new_whales)
                    logger.info(f"🐋 {len(new_whales)} nouvelles transactions whale détectées!")
                    
                    for whale in new_whales:
                        amount = whale['amount_usd']
                        tx_type = whale['transaction_type'].upper()
                        dex = whale['dex_id']
                        
                        if amount >= CRITICAL_THRESHOLD_USD:
                            logger.warning(f"🚨 CRITIQUE: ${amount:,.0f} {tx_type} sur {dex}")
                        else:
                            logger.info(f"💰 WHALE: ${amount:,.0f} {tx_type} sur {dex}")
                
                last_check = datetime.now()
                self.stats['total_checks'] += 1
                
                await asyncio.sleep(10)  # Check toutes les 10 secondes
                
            except Exception as e:
                logger.error(f"❌ Erreur monitoring whale: {e}")
                self.stats['errors'] += 1
                await asyncio.sleep(30)
    
    def get_new_whale_transactions(self, since: datetime) -> List[Dict]:
        """Récupérer les nouvelles transactions whale"""
        conn = sqlite3.connect(self.database_path)
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                SELECT * FROM whale_transactions_live 
                WHERE created_at > ?
                ORDER BY timestamp DESC
                LIMIT 50
            ''', (since,))
            
            columns = [desc[0] for desc in cursor.description]
            results = []
            
            for row in cursor.fetchall():
                results.append(dict(zip(columns, row)))
            
            return results
            
        except Exception as e:
            logger.error(f"❌ Erreur récupération nouvelles whales: {e}")
            return []
        finally:
            conn.close()
    
    async def test_api_endpoints(self):
        """Tester les endpoints API périodiquement"""
        logger.info("🔌 Démarrage test API endpoints...")
        
        while self.running:
            try:
                # Test résumé whale
                summary = whale_api.get_whale_activity_summary()
                self.stats['api_calls'] += 1
                
                if summary:
                    logger.info(f"📊 API Summary: {summary['total_transactions']} tx, ${summary['total_volume_usd']:,.0f} volume")
                else:
                    logger.warning("⚠️ API Summary retourne vide")
                
                # Test activité récente
                recent = whale_api.get_recent_whale_activity(hours=1, limit=5)
                self.stats['api_calls'] += 1
                
                logger.info(f"📈 API Recent: {len(recent)} transactions dernière heure")
                
                await asyncio.sleep(60)  # Test API toutes les minutes
                
            except Exception as e:
                logger.error(f"❌ Erreur test API: {e}")
                self.stats['errors'] += 1
                await asyncio.sleep(120)
    
    async def simulate_websocket_logs(self):
        """Simuler des logs WebSocket pour tester le parsing"""
        logger.info("📡 Démarrage simulation WebSocket...")
        
        # Logs de test réalistes
        test_logs_scenarios = [
            {
                'signature': f'simulated_jupiter_{int(time.time())}',
                'logs': [
                    'Program JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4 invoke [1]',
                    'Program log: Instruction: Route',
                    'Program TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA invoke [2]',
                    'Program data: large_swap_detected'
                ]
            },
            {
                'signature': f'simulated_raydium_{int(time.time())}',
                'logs': [
                    'Program 675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8 invoke [1]',
                    'Program log: swap_base_in',
                    'Program TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA invoke [2]'
                ]
            },
            {
                'signature': f'simulated_pumpfun_{int(time.time())}',
                'logs': [
                    'Program 6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P invoke [1]',
                    'Program log: Instruction: Buy',
                    'Program data: pump_buy_large_amount'
                ]
            }
        ]
        
        while self.running:
            try:
                for scenario in test_logs_scenarios:
                    if not self.running:
                        break
                    
                    logger.info(f"🧪 Test parsing: {scenario['signature']}")
                    
                    # Simuler le traitement WebSocket
                    await process_websocket_logs_for_whales(
                        scenario['signature'], 
                        scenario['logs']
                    )
                    
                    await asyncio.sleep(30)  # Attendre entre simulations
                
                await asyncio.sleep(300)  # Cycle complet toutes les 5 minutes
                
            except Exception as e:
                logger.error(f"❌ Erreur simulation WebSocket: {e}")
                self.stats['errors'] += 1
                await asyncio.sleep(180)
    
    async def display_stats(self):
        """Afficher les statistiques périodiquement"""
        while self.running:
            try:
                uptime = datetime.now() - self.stats['start_time']
                
                logger.info("📊 === STATS WHALE TEST RUNNER ===")
                logger.info(f"   ⏱️  Uptime: {uptime}")
                logger.info(f"   🔍 Checks totaux: {self.stats['total_checks']}")
                logger.info(f"   🐋 Whales détectées: {self.stats['whales_detected']}")
                logger.info(f"   🔌 Appels API: {self.stats['api_calls']}")
                logger.info(f"   ❌ Erreurs: {self.stats['errors']}")
                
                # Stats base de données
                conn = sqlite3.connect(self.database_path)
                cursor = conn.cursor()
                
                cursor.execute("SELECT COUNT(*) FROM whale_transactions_live WHERE timestamp > datetime('now', '-1 hour')")
                whales_1h = cursor.fetchone()[0]
                
                cursor.execute("SELECT COUNT(*) FROM whale_transactions_live WHERE timestamp > datetime('now', '-24 hours')")
                whales_24h = cursor.fetchone()[0]
                
                conn.close()
                
                logger.info(f"   💾 DB Whales 1h: {whales_1h}")
                logger.info(f"   💾 DB Whales 24h: {whales_24h}")
                logger.info("=" * 40)
                
                await asyncio.sleep(120)  # Stats toutes les 2 minutes
                
            except Exception as e:
                logger.error(f"❌ Erreur affichage stats: {e}")
                await asyncio.sleep(180)
    
    async def check_system_health(self):
        """Vérifier la santé du système"""
        while self.running:
            try:
                # Vérifier que le whale_detector est actif
                if not whale_detector.is_running:
                    logger.warning("⚠️ Whale detector n'est pas en cours d'exécution!")
                
                # Vérifier la base de données
                conn = sqlite3.connect(self.database_path)
                cursor = conn.cursor()
                
                # Test requête simple
                cursor.execute("SELECT COUNT(*) FROM whale_transactions_live")
                total_whales = cursor.fetchone()[0]
                
                if total_whales == 0:
                    logger.warning("⚠️ Aucune transaction whale en base!")
                
                conn.close()
                
                # Vérifier les logs récents
                recent_errors = self.stats['errors']
                if recent_errors > 10:
                    logger.warning(f"⚠️ Nombre d'erreurs élevé: {recent_errors}")
                
                await asyncio.sleep(300)  # Health check toutes les 5 minutes
                
            except Exception as e:
                logger.error(f"❌ Erreur health check: {e}")
                self.stats['errors'] += 1
                await asyncio.sleep(300)
    
    def display_final_stats(self):
        """Afficher les stats finales"""
        uptime = datetime.now() - self.stats['start_time'] if self.stats['start_time'] else timedelta(0)
        
        logger.info("🏁 === STATS FINALES WHALE TEST RUNNER ===")
        logger.info(f"   ⏱️  Durée totale: {uptime}")
        logger.info(f"   🔍 Checks totaux: {self.stats['total_checks']}")
        logger.info(f"   🐋 Whales détectées: {self.stats['whales_detected']}")
        logger.info(f"   🔌 Appels API: {self.stats['api_calls']}")
        logger.info(f"   ❌ Erreurs: {self.stats['errors']}")
        
        if uptime.total_seconds() > 0:
            rate = self.stats['whales_detected'] / (uptime.total_seconds() / 3600)
            logger.info(f"   📈 Taux détection: {rate:.2f} whales/heure")
        
        logger.info("🎉 Test runner terminé avec succès!")

async def main():
    """Point d'entrée principal"""
    
    print("🐋 === WHALE DETECTION CONTINUOUS TEST RUNNER === 🐋")
    print("Ce script va tester la détection whale en continu.")
    print("Appuyez sur Ctrl+C pour arrêter proprement.\n")
    
    # Vérifier les dépendances
    if not os.path.exists("tokens.db"):
        print("⚠️ Warning: tokens.db n'existe pas, il sera créé automatiquement")
    
    try:
        runner = WhaleTestRunner()
        await runner.start_continuous_testing()
        
    except KeyboardInterrupt:
        logger.info("👋 Arrêt demandé par l'utilisateur")
    except Exception as e:
        logger.error(f"❌ Erreur fatale: {e}", exc_info=True)
        return 1
    
    return 0

if __name__ == "__main__":
    try:
        exit_code = asyncio.run(main())
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\n👋 Au revoir!")
        sys.exit(0)