# Correction pour Windows - Remplacer le début du fichier creator_analysis_service.py

#!/usr/bin/env python3
"""
Creator Analysis Service - Service autonome pour l'analyse des créateurs
Version Windows compatible (sans emojis)
"""

import sys
import os
import time
import signal
import logging
import asyncio
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from pathlib import Path
import sqlite3

# Fix pour l'encodage Windows
if sys.platform == "win32":
    import io
    # Forcer l'encodage UTF-8 pour stdout
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.creator_analyzer import creator_analyzer
from app.database import db
from app.config import settings

# Configuration du logging SANS emojis pour Windows
class WindowsCompatibleFormatter(logging.Formatter):
    """Formatter qui remplace les emojis par du texte pour Windows"""
    
    def format(self, record):
        # Remplacer les emojis par du texte
        if hasattr(record, 'msg'):
            msg = str(record.msg)
            # Dictionnaire de remplacement des emojis
            emoji_replacements = {
                '🚀': '[START]',
                '📡': '[MONITOR]', 
                '📊': '[STATS]',
                '🔄': '[UPDATE]',
                '🆕': '[NEW]',
                '📈': '[CHART]',
                '🔍': '[SEARCH]',
                '✅': '[OK]',
                '❌': '[ERROR]',
                '⚠️': '[WARNING]',
                '🩺': '[HEALTH]',
                '💾': '[SAVE]',
                '🚨': '[ALERT]',
                '✨': '[STAR]',
                '🎯': '[TARGET]',
                '📝': '[LOG]',
                '🕐': '[TIME]',
                '👁️': '[WATCH]',
                '👋': '[STOP]',
                '🎉': '[SUCCESS]'
            }
            
            for emoji, replacement in emoji_replacements.items():
                msg = msg.replace(emoji, replacement)
            
            record.msg = msg
        
        return super().format(record)

# Configuration du logging avec formatter Windows
def setup_windows_logging():
    """Configure le logging compatible Windows"""
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    
    # Supprimer les handlers existants
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
    
    # Handler pour fichier
    file_handler = logging.FileHandler('creator_service.log', encoding='utf-8')
    file_formatter = WindowsCompatibleFormatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    file_handler.setFormatter(file_formatter)
    logger.addHandler(file_handler)
    
    # Handler pour console
    console_handler = logging.StreamHandler(sys.stdout)
    console_formatter = WindowsCompatibleFormatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)

# Configurer le logging
setup_windows_logging()
logger = logging.getLogger(__name__)

class CreatorAnalysisService:
    """
    Service autonome pour l'analyse des créateurs de tokens
    Version Windows compatible
    """
    
    def __init__(self):
        self.running = False
        self.last_token_check = datetime.now() - timedelta(minutes=10)
        self.last_bulk_update = datetime.now() - timedelta(hours=6)
        self.processed_tokens = set()
        
        # Configuration
        self.config = {
            'new_token_check_interval': 30,     # Vérifier nouveaux tokens toutes les 30s
            'bulk_update_interval_hours': 6,    # Mise à jour complète toutes les 6h
            'outcome_check_interval': 300,      # Vérifier outcomes toutes les 5min
            'max_tokens_per_batch': 50,         # Max tokens à traiter par lot
            'creator_cache_duration_hours': 1,  # Cache créateur 1h
        }
        
        # Statistiques
        self.stats = {
            'service_start_time': datetime.now(),
            'tokens_processed': 0,
            'creators_updated': 0,
            'alerts_generated': 0,
            'errors': 0,
            'last_activity': datetime.now()
        }
        
        # Gestion des signaux pour arrêt propre
        signal.signal(signal.SIGINT, self._signal_handler)
        if hasattr(signal, 'SIGTERM'):  # SIGTERM n'existe pas sur Windows
            signal.signal(signal.SIGTERM, self._signal_handler)
    
    def _signal_handler(self, signum, frame):
        """Gestionnaire de signaux pour arrêt propre"""
        logger.info(f"Received signal {signum}, shutting down gracefully...")
        self.running = False
    
    async def start(self):
        """Démarre le service"""
        logger.info("[START] Starting Creator Analysis Service...")
        logger.info(f"Config: {self.config}")
        
        self.running = True
        
        # Tâches principales
        tasks = [
            asyncio.create_task(self._new_token_monitor()),
            asyncio.create_task(self._outcome_monitor()),
            asyncio.create_task(self._periodic_bulk_update()),
            asyncio.create_task(self._health_monitor()),
        ]
        
        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            logger.info("Service tasks cancelled")
        except Exception as e:
            logger.error(f"Unexpected error in service: {e}")
        finally:
            logger.info("Creator Analysis Service stopped")
    
    async def _new_token_monitor(self):
        """Surveille les nouveaux tokens et analyse leurs créateurs"""
        logger.info("[MONITOR] Starting new token monitor...")
        
        while self.running:
            try:
                # Récupérer les nouveaux tokens depuis la dernière vérification
                new_tokens = self._get_new_tokens_since(self.last_token_check)
                
                if new_tokens:
                    logger.info(f"[NEW] Found {len(new_tokens)} new tokens to process")
                    
                    for token in new_tokens:
                        await self._process_new_token(token)
                        await asyncio.sleep(1)  # Petite pause entre tokens
                    
                    self.last_token_check = datetime.now()
                
                await asyncio.sleep(self.config['new_token_check_interval'])
                
            except Exception as e:
                logger.error(f"[ERROR] Error in new token monitor: {e}")
                self.stats['errors'] += 1
                await asyncio.sleep(60)
    
    async def _outcome_monitor(self):
        """Surveille les changements d'outcomes des tokens"""
        logger.info("[STATS] Starting outcome monitor...")
        
        while self.running:
            try:
                # Vérifier les tokens avec outcomes récemment mis à jour
                updated_outcomes = self._get_updated_outcomes()
                
                if updated_outcomes:
                    logger.info(f"[CHART] Found {len(updated_outcomes)} outcome updates to process")
                    
                    # Grouper par créateur pour éviter les doublons
                    creators_to_update = set()
                    for outcome in updated_outcomes:
                        creator = self._get_token_creator(outcome['token_address'])
                        if creator:
                            creators_to_update.add(creator)
                    
                    # Mettre à jour les créateurs affectés
                    for creator_address in creators_to_update:
                        await self._update_creator_performance(creator_address)
                        await asyncio.sleep(2)
                
                await asyncio.sleep(self.config['outcome_check_interval'])
                
            except Exception as e:
                logger.error(f"[ERROR] Error in outcome monitor: {e}")
                self.stats['errors'] += 1
                await asyncio.sleep(120)
    
    async def _periodic_bulk_update(self):
        """Mise à jour périodique complète de tous les créateurs"""
        logger.info("[UPDATE] Starting periodic bulk update monitor...")
        
        while self.running:
            try:
                time_since_last = datetime.now() - self.last_bulk_update
                hours_since_last = time_since_last.total_seconds() / 3600
                
                if hours_since_last >= self.config['bulk_update_interval_hours']:
                    logger.info("[UPDATE] Starting scheduled bulk update...")
                    await self._run_bulk_update()
                    self.last_bulk_update = datetime.now()
                
                # Vérifier toutes les heures
                await asyncio.sleep(3600)
                
            except Exception as e:
                logger.error(f"[ERROR] Error in bulk update monitor: {e}")
                self.stats['errors'] += 1
                await asyncio.sleep(1800)
    
    async def _health_monitor(self):
        """Monitore la santé du service et génère des rapports"""
        logger.info("[HEALTH] Starting health monitor...")
        
        while self.running:
            try:
                # Générer un rapport de santé toutes les 30 minutes
                await asyncio.sleep(1800)
                
                if self.running:
                    self._log_health_report()
                
            except Exception as e:
                logger.error(f"[ERROR] Error in health monitor: {e}")
    
    async def _process_new_token(self, token: Dict[str, Any]):
        """Traite un nouveau token"""
        try:
            token_address = token['address']
            creator_address = token['creator']
            
            logger.info(f"[SEARCH] Processing new token {token_address[:10]}... from creator {creator_address[:10]}...")
            
            # Analyser le créateur
            performance = creator_analyzer.analyze_creator(creator_address, force_refresh=True)
            
            # Mettre à jour en base
            success = creator_analyzer.update_creator_in_database(performance)
            
            if success:
                # Mettre à jour le token avec les infos créateur
                self._update_token_creator_info(token_address, performance)
                
                # Générer des alertes
                alerts = self._generate_token_alerts(token, performance)
                
                self.stats['tokens_processed'] += 1
                self.stats['creators_updated'] += 1
                self.stats['alerts_generated'] += len(alerts)
                
                # Log des alertes importantes
                for alert in alerts:
                    if alert['level'] in ['CRITICAL', 'HIGH']:
                        logger.warning(f"[ALERT] {alert['type']}: {alert['message']} - Token: {token_address[:10]}...")
                    elif alert['level'] == 'POSITIVE':
                        logger.info(f"[STAR] {alert['type']}: {alert['message']} - Token: {token_address[:10]}...")
                
                logger.info(f"[OK] Token processed: {creator_address[:10]}... - "
                           f"Score: {performance.reputation_score:.1f}, "
                           f"Blacklisted: {performance.is_blacklisted}")
            
            self.processed_tokens.add(token_address)
            self.stats['last_activity'] = datetime.now()
            
        except Exception as e:
            logger.error(f"[ERROR] Error processing token {token['address']}: {e}")
            self.stats['errors'] += 1
    
    async def _update_creator_performance(self, creator_address: str):
        """Met à jour les performances d'un créateur"""
        try:
            logger.info(f"[UPDATE] Updating creator performance: {creator_address[:10]}...")
            
            performance = creator_analyzer.analyze_creator(creator_address, force_refresh=True)
            success = creator_analyzer.update_creator_in_database(performance)
            
            if success:
                self.stats['creators_updated'] += 1
                logger.info(f"[OK] Creator updated: {creator_address[:10]}... - Score: {performance.reputation_score:.1f}")
            
            self.stats['last_activity'] = datetime.now()
            
        except Exception as e:
            logger.error(f"[ERROR] Error updating creator {creator_address}: {e}")
            self.stats['errors'] += 1
    
    async def _run_bulk_update(self):
        """Exécute une mise à jour complète de tous les créateurs"""
        try:
            logger.info("[STATS] Starting bulk creator update...")
            
            # Récupérer les créateurs actifs
            active_creators = self._get_active_creators(days_back=30)
            
            if not active_creators:
                logger.info("No active creators found")
                return
            
            logger.info(f"Updating {len(active_creators)} active creators...")
            
            # Traiter par lots
            batch_size = 20
            total_updated = 0
            
            for i in range(0, len(active_creators), batch_size):
                if not self.running:
                    break
                
                batch = active_creators[i:i + batch_size]
                logger.info(f"Processing batch {i//batch_size + 1}/{(len(active_creators) + batch_size - 1)//batch_size}")
                
                for creator_address in batch:
                    if not self.running:
                        break
                    
                    await self._update_creator_performance(creator_address)
                    await asyncio.sleep(0.5)
                    total_updated += 1
                
                # Pause entre lots
                await asyncio.sleep(2)
            
            logger.info(f"[OK] Bulk update completed: {total_updated} creators updated")
            
        except Exception as e:
            logger.error(f"[ERROR] Error in bulk update: {e}")
            self.stats['errors'] += 1
    
    def _get_new_tokens_since(self, since_time: datetime) -> List[Dict[str, Any]]:
        """Récupère les nouveaux tokens depuis une date donnée"""
        try:
            with db.get_connection() as conn:
                cursor = conn.cursor()
                
                cursor.execute("""
                    SELECT address, creator, name, symbol, created_at
                    FROM pump_tokens
                    WHERE created_at > ?
                    ORDER BY created_at DESC
                    LIMIT ?
                """, (
                    since_time.isoformat(),
                    self.config['max_tokens_per_batch']
                ))
                
                return [dict(row) for row in cursor.fetchall()]
                
        except Exception as e:
            logger.error(f"[ERROR] Error getting new tokens: {e}")
            return []
    
    def _get_updated_outcomes(self) -> List[Dict[str, Any]]:
        """Récupère les outcomes récemment mis à jour"""
        try:
            with db.get_connection() as conn:
                cursor = conn.cursor()
                
                # Vérifier s'il y a une table token_outcomes_extended
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='token_outcomes_extended'")
                
                if cursor.fetchone():
                    cursor.execute("""
                        SELECT token_address, outcome_type, updated_at
                        FROM token_outcomes_extended
                        WHERE updated_at > ?
                        ORDER BY updated_at DESC
                        LIMIT 100
                    """, ((datetime.now() - timedelta(minutes=10)).isoformat(),))
                    
                    return [dict(row) for row in cursor.fetchall()]
                
                return []
                
        except Exception as e:
            logger.error(f"[ERROR] Error getting updated outcomes: {e}")
            return []
    
    def _get_token_creator(self, token_address: str) -> Optional[str]:
        """Récupère le créateur d'un token"""
        try:
            with db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT creator FROM pump_tokens WHERE address = ?", (token_address,))
                result = cursor.fetchone()
                return result['creator'] if result else None
                
        except Exception as e:
            logger.error(f"[ERROR] Error getting token creator: {e}")
            return None
    
    def _get_active_creators(self, days_back: int = 30) -> List[str]:
        """Récupère les créateurs actifs"""
        try:
            cutoff_date = (datetime.now() - timedelta(days=days_back)).isoformat()
            
            with db.get_connection() as conn:
                cursor = conn.cursor()
                
                cursor.execute("""
                    SELECT DISTINCT creator 
                    FROM pump_tokens 
                    WHERE created_at >= ?
                    ORDER BY created_at DESC
                """, (cutoff_date,))
                
                return [row['creator'] for row in cursor.fetchall()]
                
        except Exception as e:
            logger.error(f"[ERROR] Error getting active creators: {e}")
            return []
    
    def _update_token_creator_info(self, token_address: str, performance):
        """Met à jour le token avec les infos de son créateur"""
        try:
            with db.get_connection() as conn:
                cursor = conn.cursor()
                
                cursor.execute("""
                    UPDATE pump_tokens 
                    SET 
                        creator_reputation_score = ?,
                        creator_risk_score = ?,
                        creator_is_blacklisted = ?,
                        creator_total_previous_tokens = ?,
                        creator_success_rate = ?
                    WHERE address = ?
                """, (
                    performance.reputation_score,
                    performance.risk_score,
                    performance.is_blacklisted,
                    performance.total_tokens,
                    performance.success_rate,
                    token_address
                ))
                
                conn.commit()
                
        except Exception as e:
            logger.error(f"[ERROR] Error updating token creator info: {e}")
    
    def _generate_token_alerts(self, token: Dict[str, Any], performance) -> List[Dict[str, Any]]:
        """Génère des alertes pour un token"""
        alerts = []
        
        if performance.is_blacklisted:
            alerts.append({
                "type": "BLACKLISTED_CREATOR",
                "level": "CRITICAL",
                "message": f"Token de createur blackliste: {performance.blacklist_reason}",
                "recommendation": "EVITER ABSOLUMENT"
            })
        elif performance.risk_score >= 80:
            alerts.append({
                "type": "HIGH_RISK_CREATOR",
                "level": "HIGH",
                "message": f"Createur tres risque (score: {performance.risk_score:.1f})",
                "recommendation": "PRUDENCE EXTREME"
            })
        elif performance.reputation_score >= 80 and performance.success_rate >= 0.6:
            alerts.append({
                "type": "EXCELLENT_CREATOR",
                "level": "POSITIVE",
                "message": f"Createur excellent (score: {performance.reputation_score:.1f}, succes: {performance.success_rate*100:.1f}%)",
                "recommendation": "OPPORTUNITE INTERESSANTE"
            })
        
        return alerts
    
    def _log_health_report(self):
        """Log un rapport de santé du service"""
        uptime = datetime.now() - self.stats['service_start_time']
        
        logger.info("[HEALTH] Service Health Report:")
        logger.info(f"   - Uptime: {uptime}")
        logger.info(f"   - Tokens processed: {self.stats['tokens_processed']}")
        logger.info(f"   - Creators updated: {self.stats['creators_updated']}")
        logger.info(f"   - Alerts generated: {self.stats['alerts_generated']}")
        logger.info(f"   - Errors: {self.stats['errors']}")
        logger.info(f"   - Last activity: {self.stats['last_activity']}")

async def main():
    """Point d'entrée principal"""
    print("[START] Creator Analysis Service")
    print("=" * 50)
    
    # Vérifier la base de données
    try:
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM pump_tokens")
            token_count = cursor.fetchone()[0]
            print(f"[OK] Database connection OK - {token_count} tokens found")
    except Exception as e:
        print(f"[ERROR] Database connection failed: {e}")
        return
    
    # Démarrer le service
    service = CreatorAnalysisService()
    
    try:
        await service.start()
    except KeyboardInterrupt:
        logger.info("Service interrupted by user")
    except Exception as e:
        logger.error(f"Service failed: {e}")
    finally:
        logger.info("Creator Analysis Service shutdown complete")

if __name__ == "__main__":
    asyncio.run(main())