# data_processor.py
import sqlite3
import logging
from datetime import datetime
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

class DataProcessor:
    def __init__(self, db_path: str = "snipers.db"):
        self.db_path = db_path
    
    def handle_pool_creation(self, tx_data: Dict[Any, Any]):
        """Traite la création d'un nouveau pool"""
        try:
            # Extraction des données Helius (structure simplifiée)
            pool_info = self.extract_pool_info(tx_data)
            
            if pool_info:
                self.save_new_pool(pool_info)
                logger.info(f"✅ Nouveau pool créé: {pool_info['pool_address']}")
        
        except Exception as e:
            logger.error(f"Erreur traitement pool: {str(e)}")
    
    def handle_swap(self, tx_data: Dict[Any, Any]):
        """Traite une transaction de swap"""
        try:
            swap_info = self.extract_swap_info(tx_data)
            
            if swap_info:
                # Calcul du timing par rapport à la création du pool
                reaction_time = self.calculate_reaction_time(
                    swap_info['pool_address'], 
                    swap_info['timestamp']
                )
                
                # Sauvegarde du swap
                self.save_swap(swap_info, reaction_time)
                
                # Mise à jour du score sniper si swap rapide
                if reaction_time and reaction_time < 5.0:  # Moins de 5 secondes
                    self.update_sniper_score(swap_info['buyer_address'])
                    logger.info(f"🎯 Swap rapide détecté: {swap_info['buyer_address']} en {reaction_time:.2f}s")
        
        except Exception as e:
            logger.error(f"Erreur traitement swap: {str(e)}")
    
    def extract_pool_info(self, tx_data: Dict[Any, Any]) -> Optional[Dict[str, Any]]:
        """Extrait les informations du pool depuis les données Helius"""
        # Cette fonction dépend de la structure exacte des données Helius
        # Pour l'instant, structure simplifiée pour tester
        
        return {
            'pool_address': tx_data.get('accountKeys', [{}])[0].get('pubkey', ''),
            'token_address': 'token_address_extracted',  # À implémenter
            'market_address': 'market_address_extracted',  # À implémenter
            'timestamp': datetime.now()
        }
    
    def save_new_pool(self, pool_info: Dict[str, Any]):
        """Sauvegarde un nouveau pool en base"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Insert token si nouveau
        cursor.execute('''
            INSERT OR IGNORE INTO tokens (address, name, symbol)
            VALUES (?, ?, ?)
        ''', (pool_info['token_address'], 'Unknown', 'UNK'))
        
        # Insert pool
        cursor.execute('''
            INSERT OR REPLACE INTO pools (address, token_address, market_address, created_at)
            VALUES (?, ?, ?, ?)
        ''', (
            pool_info['pool_address'],
            pool_info['token_address'],
            pool_info['market_address'],
            pool_info['timestamp']
        ))
        
        conn.commit()
        conn.close()