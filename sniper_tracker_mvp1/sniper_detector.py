# sniper_detector.py
import sqlite3
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

class SniperDetector:
    def __init__(self, db_path: str = "snipers.db"):
        self.db_path = db_path
    
    def update_sniper_score(self, wallet_address: str):
        """Met à jour le score sniper d'un portefeuille"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Récupération des swaps rapides de ce wallet
        cursor.execute('''
            SELECT seconds_after_pool_creation, timestamp
            FROM swaps
            WHERE buyer_address = ? AND seconds_after_pool_creation < 10.0
            ORDER BY timestamp DESC
        ''', (wallet_address,))
        
        fast_swaps = cursor.fetchall()
        
        if len(fast_swaps) >= 3:  # Minimum 3 swaps rapides
            # Calculs
            snipe_count = len(fast_swaps)
            avg_reaction_time = sum(swap[0] for swap in fast_swaps) / len(fast_swaps)
            
            # Score basique
            confidence_score = min(snipe_count * 0.15, 1.0)
            
            # Bonus pour vitesse
            if avg_reaction_time < 2.0:
                confidence_score *= 1.5
            
            confidence_score = min(confidence_score, 1.0)
            
            # Mise à jour en base
            cursor.execute('''
                INSERT OR REPLACE INTO snipers 
                (wallet_address, snipe_count, avg_reaction_time, confidence_score, last_updated)
                VALUES (?, ?, ?, ?, ?)
            ''', (wallet_address, snipe_count, avg_reaction_time, confidence_score, datetime.now()))
            
            logger.info(f"📊 Sniper mis à jour: {wallet_address[:8]}... Score: {confidence_score:.2f}")
        
        conn.commit()
        conn.close()
    
    def get_top_snipers(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Récupère la liste des meilleurs snipers"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT wallet_address, snipe_count, avg_reaction_time, confidence_score, last_updated
            FROM snipers
            WHERE confidence_score > 0.3
            ORDER BY confidence_score DESC, snipe_count DESC
            LIMIT ?
        ''', (limit,))
        
        snipers = []
        for row in cursor.fetchall():
            snipers.append({
                'wallet_address': row[0],
                'snipe_count': row[1],
                'avg_reaction_time': row[2],
                'confidence_score': row[3],
                'last_updated': row[4]
            })
        
        conn.close()
        return snipers