# tests/test_integration.py
import unittest
import sqlite3
import json
from datetime import datetime
import sys
import os

# Ajout du path parent pour les imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data_processor import DataProcessor
from sniper_detector import SniperDetector

class TestIntegration(unittest.TestCase):
    
    def setUp(self):
        """Setup base de données de test"""
        self.test_db = "test_snipers.db"
        self.processor = DataProcessor(self.test_db)
        self.detector = SniperDetector(self.test_db)
        
        # Créer les tables
        conn = sqlite3.connect(self.test_db)
        cursor = conn.cursor()
        
        # Tables simplifiées pour les tests
        cursor.execute('''
            CREATE TABLE tokens (
                address TEXT PRIMARY KEY,
                name TEXT,
                symbol TEXT,
                created_at TIMESTAMP
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE pools (
                address TEXT PRIMARY KEY,
                token_address TEXT,
                created_at TIMESTAMP
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE swaps (
                signature TEXT PRIMARY KEY,
                pool_address TEXT,
                buyer_address TEXT,
                seconds_after_pool_creation REAL,
                timestamp TIMESTAMP
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE snipers (
                wallet_address TEXT PRIMARY KEY,
                snipe_count INTEGER,
                avg_reaction_time REAL,
                confidence_score REAL
            )
        ''')
        
        conn.commit()
        conn.close()
    
    def tearDown(self):
        """Nettoyage après tests"""
        os.remove(self.test_db)
    
    def test_sniper_detection_flow(self):
        """Test complet du flow de détection"""
        
        # Simulation d'un nouveau pool
        pool_data = {
            'pool_address': 'pool123',
            'token_address': 'token123',
            'market_address': 'market123',
            'timestamp': datetime.now()
        }
        
        self.processor.save_new_pool(pool_data)
        
        # Simulation de swaps rapides par le même wallet
        wallet_address = "sniper_wallet_123"
        
        for i in range(5):  # 5 swaps rapides
            swap_data = {
                'signature': f'swap_{i}',
                'pool_address': 'pool123',
                'buyer_address': wallet_address,
                'timestamp': datetime.now()
            }
            
            reaction_time = 1.5 + (i * 0.2)  # Entre 1.5 et 2.3 secondes
            self.processor.save_swap(swap_data, reaction_time)
        
        # Test de détection du sniper
        self.detector.update_sniper_score(wallet_address)
        
        # Vérification
        snipers = self.detector.get_top_snipers(limit=10)
        
        self.assertEqual(len(snipers), 1)
        self.assertEqual(snipers[0]['wallet_address'], wallet_address)
        self.assertEqual(snipers[0]['snipe_count'], 5)
        self.assertGreater(snipers[0]['confidence_score'], 0.5)
        
        print("✅ Test de détection sniper réussi")

if __name__ == "__main__":
    unittest.main()