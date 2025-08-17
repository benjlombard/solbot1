#!/usr/bin/env python3
"""
Script de détection et mise à jour des tokens ruggés - VERSION CONTINUE
Analyse les tokens suspects et confirme les rug pulls avant mise à jour
Fonctionne en continu avec vérifications périodiques
Version sans emojis pour compatibilité Windows
"""

import sqlite3
import logging
from datetime import datetime
from typing import Set, List, Tuple
import sys
import os
import time
import signal
import threading
from pathlib import Path

# Variables globales pour la gestion du cycle
running = True
cycle_count = 0

# Configuration du logging compatible Windows
def setup_logging():
    """Configuration du système de logging"""
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    
    log_filename = log_dir / f'rug_pull_continuous_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log'
    
    # Configuration du logger
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_filename, encoding='utf-8'),
            logging.StreamHandler(sys.stdout)
        ]
    )
    
    return logging.getLogger(__name__)

# Gestionnaire pour arrêt propre
def signal_handler(signum, frame):
    """Gestionnaire pour arrêt propre avec Ctrl+C"""
    global running
    logger.info("[ARRET] Signal d'arret recu - Arret en cours...")
    running = False

class RugPullDetector:
    """Détecteur et gestionnaire des rug pulls"""
    
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.connection = None
        self.last_check_time = None
        self.stats = {
            'total_cycles': 0,
            'total_tokens_updated': 0,
            'total_history_updated': 0,
            'last_detection_time': None
        }
        
    def connect(self):
        """Connexion à la base de données avec retry"""
        max_retries = 3
        retry_delay = 5
        
        for attempt in range(max_retries):
            try:
                self.connection = sqlite3.connect(self.db_path, timeout=30.0)
                self.connection.row_factory = sqlite3.Row
                # Test de la connexion
                self.connection.execute("SELECT 1").fetchone()
                logger.info(f"[OK] Connexion etablie avec {self.db_path}")
                return True
            except Exception as e:
                logger.error(f"[ERREUR] Tentative {attempt + 1}/{max_retries} - Erreur connexion DB: {e}")
                if attempt < max_retries - 1:
                    logger.info(f"[RETRY] Nouvelle tentative dans {retry_delay}s...")
                    time.sleep(retry_delay)
                else:
                    logger.error("[ECHEC] Impossible de se connecter après plusieurs tentatives")
                    return False
    
    def disconnect(self):
        """Fermeture de la connexion"""
        if self.connection:
            try:
                self.connection.close()
                logger.debug("[FERME] Connexion fermee")
            except Exception as e:
                logger.error(f"[ERREUR] Erreur fermeture connexion: {e}")
    
    def reconnect_if_needed(self):
        """Reconnecte si la connexion est fermée"""
        try:
            if self.connection is None:
                return self.connect()
            # Test de la connexion
            self.connection.execute("SELECT 1").fetchone()
            return True
        except Exception:
            logger.warning("[RECONNECT] Connexion perdue - Reconnexion...")
            self.disconnect()
            return self.connect()
    
    def get_suspect_tokens(self) -> Set[str]:
        """
        Requête 1: Tokens suspects (liquidité disparue) - EXCLUANT DÉJÀ RUGGÉS
        """
        query = """
        SELECT DISTINCT token_address 
        FROM tokens_history th1 
        WHERE th1.liquidity_usd = 0 
          AND EXISTS (
              SELECT 1 
              FROM tokens_history th2 
              WHERE th2.token_address = th1.token_address 
                AND th2.snapshot_timestamp < th1.snapshot_timestamp 
                AND th2.liquidity_usd > 1000
          )
          AND NOT EXISTS (
              -- Exclure les tokens déjà marqués comme ruggés
              SELECT 1 
              FROM tokens t 
              WHERE t.address = th1.token_address 
                AND t.is_rugged = 1
          )
        """
        
        try:
            cursor = self.connection.execute(query)
            suspects = {row['token_address'] for row in cursor.fetchall()}
            logger.info(f"[RECHERCHE] Requete 1 - Tokens suspects trouves: {len(suspects)}")
            return suspects
        except Exception as e:
            logger.error(f"[ERREUR] Erreur requete suspects: {e}")
            return set()
    
    def get_confirmed_rugs(self) -> Set[str]:
        """
        Requête 2: Rug pulls confirmés (critères stricts) - EXCLUANT DÉJÀ RUGGÉS
        """
        query = """
        SELECT DISTINCT th1.token_address
        FROM tokens_history th1
        WHERE th1.liquidity_usd = 0
          AND th1.volume_24h > 100  -- Volume suspect avec liquidité = 0
          AND EXISTS (
              SELECT 1 
              FROM tokens_history th2 
              WHERE th2.token_address = th1.token_address 
                AND th2.snapshot_timestamp < th1.snapshot_timestamp 
                AND th2.liquidity_usd > 1000
                AND th2.volume_24h > 100  -- Était actif avant
          )
          AND NOT EXISTS (
              -- Exclure si la liquidité est revenue (migration temporaire)
              SELECT 1 
              FROM tokens_history th3 
              WHERE th3.token_address = th1.token_address 
                AND th3.snapshot_timestamp > th1.snapshot_timestamp 
                AND th3.liquidity_usd > 0
          )
          AND NOT EXISTS (
              -- Exclure les tokens déjà marqués comme ruggés
              SELECT 1 
              FROM tokens t 
              WHERE t.address = th1.token_address 
                AND t.is_rugged = 1
          )
        """
        
        try:
            cursor = self.connection.execute(query)
            confirmed = {row['token_address'] for row in cursor.fetchall()}
            logger.info(f"[ALERTE] Requete 2 - Rug pulls confirmes: {len(confirmed)}")
            return confirmed
        except Exception as e:
            logger.error(f"[ERREUR] Erreur requete confirmes: {e}")
            return set()
    
    def analyze_token_sets(self, suspects: Set[str], confirmed: Set[str]) -> Tuple[Set[str], Set[str], Set[str]]:
        """Analyse les ensembles de tokens"""
        
        # Tokens présents dans les deux requêtes (à traiter)
        to_update = suspects.intersection(confirmed)
        
        # Tokens seulement suspects (pas de mise à jour)
        only_suspects = suspects - confirmed
        
        # Tokens seulement confirmés (cas improbable mais possible)
        only_confirmed = confirmed - suspects
        
        if to_update:
            logger.info("=" * 50)
            logger.info("[ANALYSE] NOUVEAUX RUG PULLS DETECTES:")
            logger.info(f"   [CIBLE] Tokens a mettre a jour: {len(to_update)}")
            logger.info(f"   [EXCLUS] Tokens seulement suspects: {len(only_suspects)}")
            logger.info(f"   [BIZARR] Tokens seulement confirmes: {len(only_confirmed)}")
            logger.info("=" * 50)
        
        return to_update, only_suspects, only_confirmed
    
    def get_rug_timestamp(self, token_address: str) -> int:
        """Récupère le timestamp du premier rug détecté"""
        query = """
        SELECT MIN(snapshot_timestamp) as rug_timestamp
        FROM tokens_history th
        WHERE th.token_address = ?
          AND th.liquidity_usd = 0
          AND EXISTS (
              SELECT 1 
              FROM tokens_history th2 
              WHERE th2.token_address = th.token_address 
                AND th2.snapshot_timestamp < th.snapshot_timestamp 
                AND th2.liquidity_usd > 1000
          )
        """
        
        cursor = self.connection.execute(query, (token_address,))
        result = cursor.fetchone()
        return result['rug_timestamp'] if result and result['rug_timestamp'] else 0
    
    def update_tokens_table(self, token_addresses: Set[str]) -> int:
        """
        ÉTAPE 1: Mise à jour de la table tokens
        """
        if not token_addresses:
            return 0
        
        logger.info(f"[ETAPE1] Mise a jour table tokens pour {len(token_addresses)} tokens")
        
        success_count = 0
        
        for token_address in token_addresses:
            try:
                # Récupérer le timestamp du rug
                rug_timestamp = self.get_rug_timestamp(token_address)
                
                update_query = """
                UPDATE tokens 
                SET 
                    is_rugged = 1,
                    is_dead = 1,
                    death_reason = 'RUG_PULL_DETECTED',
                    death_timestamp = ?,
                    rug_risk_score = 100,
                    risk_score = 100.0,
                    viability_score = 0.0,
                    momentum_score = -100.0,
                    liquidity_usd = 0.0,
                    liquidity_sol = 0.0,
                    liquidity_mc_ratio = 0.0,
                    volume_mc_ratio = 0.0,
                    has_low_liquidity = 1,
                    lp_providers_count = 0,
                    updated_at = CURRENT_TIMESTAMP
                WHERE address = ?
                """
                
                cursor = self.connection.execute(update_query, (rug_timestamp, token_address))
                
                if cursor.rowcount > 0:
                    success_count += 1
                    rug_date = datetime.fromtimestamp(rug_timestamp).strftime('%Y-%m-%d %H:%M:%S') if rug_timestamp > 0 else 'Unknown'
                    logger.info(f"   [OK] {token_address[:12]}... mis a jour (rug: {rug_date})")
                else:
                    logger.warning(f"   [MANQUE] {token_address[:12]}... non trouve dans table tokens")
                    
            except Exception as e:
                logger.error(f"   [ERREUR] Erreur mise a jour {token_address[:12]}...: {e}")
        
        self.connection.commit()
        logger.info(f"[SAUVE] ETAPE 1 terminee: {success_count}/{len(token_addresses)} tokens mis a jour")
        return success_count
    
    def update_tokens_history_table(self, token_addresses: Set[str]) -> int:
        """
        ÉTAPE 2: Mise à jour de la table tokens_history
        """
        if not token_addresses:
            return 0
        
        logger.info(f"[ETAPE2] Mise a jour table tokens_history pour {len(token_addresses)} tokens")
        
        total_updated = 0
        
        for token_address in token_addresses:
            try:
                # Récupérer le timestamp du rug
                rug_timestamp = self.get_rug_timestamp(token_address)
                
                update_query = """
                UPDATE tokens_history 
                SET 
                    is_rugged = 1,
                    rug_risk_score = 100,
                    risk_score = 100.0,
                    viability_score = 0.0,
                    momentum_score = -100.0,
                    has_low_liquidity = 1
                WHERE token_address = ?
                  AND snapshot_timestamp >= ?
                """
                
                cursor = self.connection.execute(update_query, (token_address, rug_timestamp))
                rows_updated = cursor.rowcount
                total_updated += rows_updated
                
                if rows_updated > 0:
                    logger.info(f"   [OK] {token_address[:12]}... - {rows_updated} snapshots mis a jour")
                else:
                    logger.warning(f"   [VIDE] {token_address[:12]}... - aucun snapshot mis a jour")
                    
            except Exception as e:
                logger.error(f"   [ERREUR] Erreur mise a jour historique {token_address[:12]}...: {e}")
        
        self.connection.commit()
        logger.info(f"[SAUVE] ETAPE 2 terminee: {total_updated} snapshots mis a jour au total")
        return total_updated
    
    def get_token_info(self, token_address: str) -> dict:
        """Récupère les infos d'un token pour les logs"""
        query = """
        SELECT symbol, name, market_cap, volume_24h 
        FROM tokens 
        WHERE address = ?
        """
        cursor = self.connection.execute(query, (token_address,))
        result = cursor.fetchone()
        return dict(result) if result else {}
    
    def log_detection_summary(self, to_update: Set[str], tokens_updated: int, history_updated: int):
        """Log du résumé de détection"""
        if to_update:
            self.stats['last_detection_time'] = datetime.now()
            self.stats['total_tokens_updated'] += tokens_updated
            self.stats['total_history_updated'] += history_updated
            
            logger.info("[DETECTION] NOUVEAUX RUG PULLS TRAITES:")
            logger.info(f"   [TOKENS] {tokens_updated} tokens marques comme rugges")
            logger.info(f"   [HISTORY] {history_updated} snapshots mis a jour")
            
            # Afficher quelques exemples
            for token in list(to_update)[:3]:
                info = self.get_token_info(token)
                symbol = info.get('symbol', 'N/A')
                logger.info(f"   [EXEMPLE] {token[:12]}... ({symbol})")
    
    def run_detection_cycle(self) -> bool:
        """Exécute un cycle de détection"""
        try:
            # Vérifier la connexion
            if not self.reconnect_if_needed():
                return False
            
            # Récupération des tokens suspects et confirmés
            suspects = self.get_suspect_tokens()
            confirmed = self.get_confirmed_rugs()
            
            # Analyse des ensembles
            to_update, only_suspects, only_confirmed = self.analyze_token_sets(suspects, confirmed)
            
            # Mise à jour si des tokens valides
            if to_update:
                logger.info("[PHASE] Nouveaux rug pulls detectes - Mise a jour en cours")
                
                # ÉTAPE 1: Table tokens
                tokens_updated = self.update_tokens_table(to_update)
                
                # ÉTAPE 2: Table tokens_history
                history_updated = self.update_tokens_history_table(to_update)
                
                # Log du résumé
                self.log_detection_summary(to_update, tokens_updated, history_updated)
                
            else:
                logger.info(f"[CLEAN] Cycle {self.stats['total_cycles']} - Aucun nouveau rug pull detecte")
            
            self.last_check_time = datetime.now()
            return True
            
        except Exception as e:
            logger.error(f"[ERREUR] Erreur pendant le cycle de detection: {e}")
            return False
    
    def print_status_report(self):
        """Affiche un rapport de statut périodique"""
        try:
            # Statistiques générales
            cursor = self.connection.execute("SELECT COUNT(*) as total FROM tokens WHERE is_rugged = 1")
            total_rugged = cursor.fetchone()['total']
            
            cursor = self.connection.execute("SELECT COUNT(*) as total FROM tokens")
            total_tokens = cursor.fetchone()['total']
            
            uptime = datetime.now() - start_time
            
            logger.info("=" * 60)
            logger.info("[RAPPORT] STATUT DU SYSTEME")
            logger.info("=" * 60)
            logger.info(f"[TEMPS] Demarrage: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
            logger.info(f"[TEMPS] Uptime: {str(uptime).split('.')[0]}")
            logger.info(f"[CYCLES] Cycles executes: {self.stats['total_cycles']}")
            logger.info(f"[DB] Total tokens: {total_tokens}")
            logger.info(f"[DB] Tokens rugges: {total_rugged}")
            logger.info(f"[STATS] Tokens rugges detectes: {self.stats['total_tokens_updated']}")
            logger.info(f"[STATS] Snapshots mis a jour: {self.stats['total_history_updated']}")
            
            if self.stats['last_detection_time']:
                last_detection = self.stats['last_detection_time'].strftime('%Y-%m-%d %H:%M:%S')
                logger.info(f"[DERNIERE] Derniere detection: {last_detection}")
            
            if self.last_check_time:
                last_check = self.last_check_time.strftime('%H:%M:%S')
                logger.info(f"[CHECK] Derniere verification: {last_check}")
            
            logger.info("=" * 60)
            
        except Exception as e:
            logger.error(f"[ERREUR] Erreur rapport de statut: {e}")

def main():
    """Fonction principale"""
    global running, cycle_count, start_time, logger
    
    # Configuration
    DB_PATH = "solana_wallet_monitor.db"
    CHECK_INTERVAL = 30  # secondes
    STATUS_REPORT_INTERVAL = 300  # 5 minutes
    
    # Initialisation du logging
    logger = setup_logging()
    start_time = datetime.now()
    
    # Gestionnaire de signaux
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    logger.info("[DEMARR] DETECTION RUG PULLS - MODE CONTINU")
    logger.info("=" * 60)
    logger.info(f"[CONFIG] Intervalle verification: {CHECK_INTERVAL}s")
    logger.info(f"[CONFIG] Rapport de statut: {STATUS_REPORT_INTERVAL}s")
    logger.info(f"[CONFIG] Base de donnees: {DB_PATH}")
    logger.info(f"[INFO] Utilisez Ctrl+C pour arreter proprement")
    logger.info("=" * 60)
    
    # Initialisation du détecteur
    detector = RugPullDetector(DB_PATH)
    
    if not detector.connect():
        logger.error("[ECHEC] Impossible de se connecter a la base de donnees")
        sys.exit(1)
    
    try:
        last_status_report = time.time()
        
        while running:
            cycle_start = time.time()
            cycle_count += 1
            detector.stats['total_cycles'] = cycle_count
            
            # Exécuter le cycle de détection
            success = detector.run_detection_cycle()
            
            if not success:
                logger.error("[ECHEC] Echec du cycle de detection - Tentative suivante dans 30s")
            
            # Rapport de statut périodique
            current_time = time.time()
            if current_time - last_status_report >= STATUS_REPORT_INTERVAL:
                detector.print_status_report()
                last_status_report = current_time
            
            # Calcul du temps d'attente
            cycle_duration = time.time() - cycle_start
            wait_time = max(0, CHECK_INTERVAL - cycle_duration)
            
            logger.info(f"[CYCLE] {cycle_count} termine en {cycle_duration:.1f}s - Attente {wait_time:.1f}s")
            
            # Attente avec vérification d'arrêt
            end_time = time.time() + wait_time
            while time.time() < end_time and running:
                time.sleep(1)
    
    except KeyboardInterrupt:
        logger.info("[ARRET] Interruption clavier detectee")
    except Exception as e:
        logger.error(f"[CRITIQUE] Erreur critique: {e}")
    finally:
        running = False
        detector.disconnect()
        
        # Rapport final
        uptime = datetime.now() - start_time
        logger.info("=" * 60)
        logger.info("[FINAL] ARRET DU SYSTEME")
        logger.info(f"[STATS] Cycles executes: {cycle_count}")
        logger.info(f"[STATS] Uptime total: {str(uptime).split('.')[0]}")
        logger.info(f"[STATS] Tokens rugges detectes: {detector.stats['total_tokens_updated']}")
        logger.info("[FINI] Arret propre du script")
        logger.info("=" * 60)

if __name__ == "__main__":
    main()