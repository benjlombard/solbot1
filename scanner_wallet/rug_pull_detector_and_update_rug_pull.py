#!/usr/bin/env python3
"""
Script de détection et mise à jour des tokens ruggés
Analyse les tokens suspects et confirme les rug pulls avant mise à jour
Version sans emojis pour compatibilité Windows
"""

import sqlite3
import logging
from datetime import datetime
from typing import Set, List, Tuple
import sys
import os

# Configuration du logging compatible Windows
log_filename = f'rug_pull_update_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log'

# Configuration du logger
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_filename, encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)

class RugPullDetector:
    """Détecteur et gestionnaire des rug pulls"""
    
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.connection = None
        
    def connect(self):
        """Connexion à la base de données"""
        try:
            self.connection = sqlite3.connect(self.db_path)
            self.connection.row_factory = sqlite3.Row
            logger.info(f"[OK] Connexion etablie avec {self.db_path}")
            return True
        except Exception as e:
            logger.error(f"[ERREUR] Erreur connexion DB: {e}")
            return False
    
    def disconnect(self):
        """Fermeture de la connexion"""
        if self.connection:
            self.connection.close()
            logger.info("[FERME] Connexion fermee")
    
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
        
        logger.info("=" * 50)
        logger.info("[ANALYSE] RESULTATS DES REQUETES:")
        logger.info(f"   [CIBLE] Tokens a mettre a jour (dans les 2 requetes): {len(to_update)}")
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
            logger.warning("[VIDE] Aucun token a mettre a jour dans la table tokens")
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
            logger.warning("[VIDE] Aucun token a mettre a jour dans tokens_history")
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
    
    def log_excluded_tokens(self, only_suspects: Set[str], only_confirmed: Set[str]):
        """Log des tokens exclus avec leurs raisons"""
        
        if only_suspects:
            logger.info(f"[EXCLUS] TOKENS SEULEMENT SUSPECTS ({len(only_suspects)}):")
            for token in list(only_suspects)[:10]:  # Limiter l'affichage
                logger.info(f"   [SUSPECT] {token[:12]}... - Liquidite = 0 mais criteres rug incomplets")
            if len(only_suspects) > 10:
                logger.info(f"   [INFO] ... et {len(only_suspects) - 10} autres")
        
        if only_confirmed:
            logger.info(f"[BIZARR] TOKENS SEULEMENT CONFIRMES ({len(only_confirmed)}):")
            for token in list(only_confirmed)[:10]:
                logger.info(f"   [ETRANGE] {token[:12]}... - Confirme mais pas dans suspects (cas rare)")
            if len(only_confirmed) > 10:
                logger.info(f"   [INFO] ... et {len(only_confirmed) - 10} autres")
    
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
    
    def generate_summary_report(self, to_update: Set[str], tokens_updated: int, history_updated: int):
        """Génère un rapport de synthèse"""
        logger.info("=" * 60)
        logger.info("[RAPPORT] SYNTHESE FINALE")
        logger.info("=" * 60)
        logger.info(f"[CIBLE] Tokens identifies pour mise a jour: {len(to_update)}")
        logger.info(f"[FAIT] Tokens table mise a jour: {tokens_updated}")
        logger.info(f"[FAIT] Snapshots history mis a jour: {history_updated}")
        logger.info(f"[DATE] Date traitement: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        if to_update:
            logger.info("")
            logger.info("[RUGGED] TOKENS MARQUES COMME RUGGES:")
            for token in list(to_update)[:5]:  # Top 5
                info = self.get_token_info(token)
                symbol = info.get('symbol', 'N/A')
                name = info.get('name', 'Unknown')
                logger.info(f"   [TOKEN] {token[:12]}... ({symbol} - {name})")
            if len(to_update) > 5:
                logger.info(f"   [INFO] ... et {len(to_update) - 5} autres")
        
        logger.info("=" * 60)

def main():
    """Fonction principale"""
    
    # Configuration
    DB_PATH = "solana_wallet_monitor.db"  # Ajustez le chemin si nécessaire
    
    logger.info("[DEMARR] DETECTION ET MISE A JOUR DES RUG PULLS")
    logger.info("=" * 60)
    
    # Initialisation
    detector = RugPullDetector(DB_PATH)
    
    if not detector.connect():
        logger.error("[ECHEC] Impossible de se connecter a la base de donnees")
        sys.exit(1)
    
    try:
        # Étape 1: Récupération des tokens suspects et confirmés
        logger.info("[PHASE1] Analyse des tokens")
        suspects = detector.get_suspect_tokens()
        confirmed = detector.get_confirmed_rugs()
        
        # Étape 2: Analyse des ensembles
        to_update, only_suspects, only_confirmed = detector.analyze_token_sets(suspects, confirmed)
        
        # Étape 3: Log des tokens exclus
        detector.log_excluded_tokens(only_suspects, only_confirmed)
        
        # Étape 4: Mise à jour si des tokens valides
        if to_update:
            logger.info("[PHASE2] Mise a jour des tables")
            
            # ÉTAPE 1: Table tokens
            tokens_updated = detector.update_tokens_table(to_update)
            
            # ÉTAPE 2: Table tokens_history
            history_updated = detector.update_tokens_history_table(to_update)
            
            # Rapport final
            detector.generate_summary_report(to_update, tokens_updated, history_updated)
            
        else:
            logger.info("[PROPRE] Aucun nouveau rug pull detecte - Base de donnees a jour")
            
            # Afficher statistiques des tokens déjà ruggés
            try:
                cursor = detector.connection.execute("SELECT COUNT(*) as total FROM tokens WHERE is_rugged = 1")
                total_rugged = cursor.fetchone()['total']
                logger.info(f"[STATS] Tokens deja marques comme rugges: {total_rugged}")
            except Exception as e:
                logger.error(f"[ERREUR] Impossible de recuperer les stats: {e}")
    
    except Exception as e:
        logger.error(f"[CRITIQUE] Erreur critique: {e}")
        sys.exit(1)
    
    finally:
        detector.disconnect()
    
    logger.info("[FINI] Script execute avec succes")

if __name__ == "__main__":
    main()