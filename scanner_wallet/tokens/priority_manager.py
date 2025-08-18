#!/usr/bin/env python3
"""
Gestionnaire principal du système de priorité des tokens
"""

import sqlite3
import time
from typing import Dict, List, Optional, Tuple
from datetime import datetime

from core.priority_config import TokenPriority, PriorityConfig
from core.logger import get_logger
from core.config import get_config
from tokens.priority_calculator import TokenPriorityCalculator

class TokenPriorityManager:
    """Gestionnaire du système de priorité des tokens"""
    
    def __init__(self, priority_config: PriorityConfig):
        self.config = priority_config
        self.calculator = TokenPriorityCalculator(priority_config)
        self.logger = get_logger('priority_manager')
        self.db_config = get_config().database
        
        self.stats = {
            'tokens_updated': 0,
            'priority_changes': 0,
            'calculation_errors': 0,
            'last_full_recalc': None
        }
    
    def get_db_connection(self) -> sqlite3.Connection:
        """Obtenir une connexion à la base de données"""
        conn = sqlite3.connect(self.db_config.get_full_path(), timeout=30.0)
        conn.row_factory = sqlite3.Row
        return conn
    
    def recalculate_all_priorities(self) -> Dict[str, int]:
        """
        Recalcule les priorités de tous les tokens
        
        Returns:
            Statistiques des changements de priorité
        """
        self.logger.info("🔄 Début du recalcul complet des priorités")
        start_time = time.time()
        
        stats = {
            'total_tokens': 0,
            'priority_changes': 0,
            'errors': 0,
            'by_priority': {level.name: 0 for level in TokenPriority}
        }
        
        try:
            with self.get_db_connection() as conn:
                cursor = conn.cursor()
                
                # Récupérer tous les tokens non supprimés
                cursor.execute("""
                    SELECT address, symbol, volume_24h, price_change_24h, market_cap, 
                           created_at, is_dead, is_rugged, price_usd, priority_level, 
                           priority_score
                    FROM tokens 
                    WHERE (no_data_available != 1 OR no_data_available IS NULL)
                    ORDER BY created_at DESC
                """)
                
                tokens = cursor.fetchall()
                stats['total_tokens'] = len(tokens)
                
                self.logger.info(f"📊 Traitement de {len(tokens)} tokens")
                
                updates = []
                priority_history = []
                
                for token in tokens:
                    try:
                        # Calculer le nouveau score et priorité
                        token_dict = dict(token)
                        new_score = self.calculator.calculate_token_score(token_dict)
                        new_priority = self.calculator.determine_priority_level(new_score, token_dict)
                        
                        old_priority = token['priority_level']
                        old_score = token['priority_score']
                        
                        # Préparer la mise à jour
                        updates.append((
                            new_priority.value,
                            new_score,
                            int(time.time()),
                            token['address']
                        ))
                        
                        # Enregistrer le changement si différent
                        if old_priority != new_priority.value:
                            stats['priority_changes'] += 1
                            priority_history.append((
                                token['address'],
                                old_priority,
                                new_priority.value,
                                old_score,
                                new_score,
                                'recalculation_complete',
                                int(time.time())
                            ))
                            
                            self.logger.debug(f"🔄 {token['address'][:8]}... : {TokenPriority(old_priority).name} -> {new_priority.name}")
                        
                        stats['by_priority'][new_priority.name] += 1
                        
                    except Exception as e:
                        stats['errors'] += 1
                        self.logger.error(f"❌ Erreur pour token {token['address']}: {e}")
                
                # Mise à jour en batch
                if updates:
                    cursor.executemany("""
                        UPDATE tokens 
                        SET priority_level = ?, priority_score = ?, 
                            last_priority_update = ?, priority_recalc_needed = 0
                        WHERE address = ?
                    """, updates)
                
                # Enregistrer l'historique
                if priority_history:
                    cursor.executemany("""
                        INSERT INTO priority_history 
                        (token_address, old_priority, new_priority, old_score, new_score, reason, timestamp)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, priority_history)
                
                conn.commit()
                
                # Mettre à jour les statistiques
                self.stats['tokens_updated'] += len(updates)
                self.stats['priority_changes'] += stats['priority_changes']
                self.stats['calculation_errors'] += stats['errors']
                self.stats['last_full_recalc'] = datetime.now()
                
                duration = time.time() - start_time
                
                self.logger.info(f"✅ Recalcul terminé en {duration:.2f}s")
                self.logger.info(f"📊 Changements: {stats['priority_changes']}, Erreurs: {stats['errors']}")
                
                # Log de la répartition
                for priority_name, count in stats['by_priority'].items():
                    if count > 0:
                        self.logger.info(f"   {priority_name}: {count} tokens")
        
        except Exception as e:
            self.logger.error(f"❌ Erreur pendant le recalcul complet: {e}")
            stats['errors'] += 1
        
        return stats
    
    def get_tokens_by_priority(self, priority: TokenPriority, limit: Optional[int] = None) -> List[str]:
        """
        Récupère les adresses des tokens d'une priorité donnée
        
        Args:
            priority: Niveau de priorité
            limit: Nombre maximum de tokens à retourner
            
        Returns:
            Liste des adresses de tokens
        """
        try:
            with self.get_db_connection() as conn:
                cursor = conn.cursor()
                
                query = """
                    SELECT address FROM tokens 
                    WHERE priority_level = ? 
                    AND (no_data_available != 1 OR no_data_available IS NULL)
                    AND (is_dead != 1 OR is_dead IS NULL)
                    ORDER BY priority_score DESC, last_priority_update ASC
                """
                
                params = [priority.value]
                
                if limit:
                    query += " LIMIT ?"
                    params.append(limit)
                
                cursor.execute(query, params)
                results = cursor.fetchall()
                
                addresses = [row['address'] for row in results]
                
                self.logger.debug(f"📋 {len(addresses)} tokens {priority.name} récupérés")
                
                return addresses
                
        except Exception as e:
            self.logger.error(f"❌ Erreur récupération tokens {priority.name}: {e}")
            return []
    
    def update_token_priority(self, token_address: str, force_recalc: bool = False) -> bool:
        """
        Met à jour la priorité d'un token spécifique
        
        Args:
            token_address: Adresse du token
            force_recalc: Forcer le recalcul même si pas nécessaire
            
        Returns:
            True si mise à jour réussie
        """
        try:
            with self.get_db_connection() as conn:
                cursor = conn.cursor()
                
                # Récupérer les données du token
                cursor.execute("""
                    SELECT * FROM tokens WHERE address = ?
                """, (token_address,))
                
                token = cursor.fetchone()
                if not token:
                    self.logger.warning(f"⚠️ Token non trouvé: {token_address}")
                    return False
                
                # Vérifier si recalcul nécessaire
                if not force_recalc and not token['priority_recalc_needed']:
                    return True
                
                # Calculer nouveau score et priorité
                token_dict = dict(token)
                new_score = self.calculator.calculate_token_score(token_dict)
                new_priority = self.calculator.determine_priority_level(new_score, token_dict)
                
                old_priority = token['priority_level']
                old_score = token['priority_score']
                
                # Mettre à jour le token
                cursor.execute("""
                    UPDATE tokens 
                    SET priority_level = ?, priority_score = ?, 
                        last_priority_update = ?, priority_recalc_needed = 0
                    WHERE address = ?
                """, (new_priority.value, new_score, int(time.time()), token_address))
                
                # Enregistrer l'historique si changement
                if old_priority != new_priority.value:
                    cursor.execute("""
                        INSERT INTO priority_history 
                        (token_address, old_priority, new_priority, old_score, new_score, reason, timestamp)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, (token_address, old_priority, new_priority.value, old_score, new_score, 
                         'individual_update', int(time.time())))
                    
                    self.stats['priority_changes'] += 1
                    self.logger.debug(f"🔄 {token_address[:8]}... : {TokenPriority(old_priority).name} -> {new_priority.name}")
                
                conn.commit()
                self.stats['tokens_updated'] += 1
                
                return True
                
        except Exception as e:
            self.logger.error(f"❌ Erreur mise à jour priorité {token_address}: {e}")
            self.stats['calculation_errors'] += 1
            return False
    
    def get_priority_distribution(self) -> Dict[str, int]:
        """Obtient la distribution actuelle des priorités"""
        try:
            with self.get_db_connection() as conn:
                cursor = conn.cursor()
                
                cursor.execute("""
                    SELECT priority_level, COUNT(*) as count
                    FROM tokens 
                    WHERE (no_data_available != 1 OR no_data_available IS NULL)
                    GROUP BY priority_level
                    ORDER BY priority_level DESC
                """)
                
                distribution = {}
                for row in cursor.fetchall():
                    priority_name = TokenPriority(row['priority_level']).name
                    distribution[priority_name] = row['count']
                
                return distribution
                
        except Exception as e:
            self.logger.error(f"❌ Erreur distribution priorités: {e}")
            return {}
    
    def save_metrics(self):
        """Sauvegarde les métriques de performance"""
        try:
            distribution = self.get_priority_distribution()
            
            with self.get_db_connection() as conn:
                cursor = conn.cursor()
                
                cursor.execute("""
                    INSERT INTO priority_metrics 
                    (timestamp, hot_tokens_count, warm_tokens_count, cold_tokens_count, 
                     dead_tokens_count, critical_tokens_count)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    int(time.time()),
                    distribution.get('HOT', 0),
                    distribution.get('WARM', 0),
                    distribution.get('COLD', 0),
                    distribution.get('DEAD', 0),
                    distribution.get('CRITICAL', 0)
                ))
                
                conn.commit()
                
        except Exception as e:
            self.logger.error(f"❌ Erreur sauvegarde métriques: {e}")
    
    def mark_tokens_for_recalculation(self, token_addresses: List[str]) -> int:
       """
       Marque des tokens pour recalcul de priorité
       
       Args:
           token_addresses: Liste des adresses à marquer
           
       Returns:
           Nombre de tokens marqués
       """
       if not token_addresses:
           return 0
           
       try:
           with self.get_db_connection() as conn:
               cursor = conn.cursor()
               
               # Marquer les tokens pour recalcul
               placeholders = ','.join(['?' for _ in token_addresses])
               cursor.execute(f"""
                   UPDATE tokens 
                   SET priority_recalc_needed = 1
                   WHERE address IN ({placeholders})
               """, token_addresses)
               
               marked_count = cursor.rowcount
               conn.commit()
               
               self.logger.debug(f"📌 {marked_count} tokens marqués pour recalcul")
               return marked_count
               
       except Exception as e:
           self.logger.error(f"❌ Erreur marquage tokens: {e}")
           return 0
   
    def get_stats(self) -> Dict:
       """Retourne les statistiques du gestionnaire"""
       distribution = self.get_priority_distribution()
       
       return {
           **self.stats,
           'priority_distribution': distribution,
           'total_managed_tokens': sum(distribution.values())
       }