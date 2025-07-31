#!/usr/bin/env python3
"""
🛡️ Script de mise à jour des scores RugCheck
Met à jour tous les tokens existants avec le bon score RugCheck (score_normalised)
"""

import asyncio
import aiohttp
import sqlite3
import time
import logging
from datetime import datetime
from typing import List, Dict, Optional, Tuple
from aiohttp import ClientSession, TCPConnector
import random
import argparse

# Configuration du logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('rugcheck_updater')

class RugCheckUpdater:
    """Classe pour mettre à jour les scores RugCheck"""
    
    def __init__(self, database_path: str = "tokens.db", batch_size: int = 5, delay: float = 2.0):
        self.database_path = database_path
        self.batch_size = batch_size
        self.delay = delay  # Délai entre requêtes pour éviter rate limiting
        self.session: Optional[ClientSession] = None
        
        # Rate limiting avancé
        self.rate_limiter = {
            'requests_per_minute': 30,  # Limite conservative : 30 req/min
            'requests_made': 0,
            'window_start': time.time(),
            'consecutive_429s': 0,
            'backoff_multiplier': 1.0
        }
        
        # Stats
        self.stats = {
            'total_processed': 0,
            'successful_updates': 0,
            'api_errors': 0,
            'no_data_found': 0,
            'scores_changed': 0,
            'scores_unchanged': 0,
            'rate_limit_hits': 0,
            'total_wait_time': 0
        }
    
    async def wait_for_rate_limit(self):
        """Gestion intelligente du rate limiting"""
        current_time = time.time()
        
        # Reset de la fenêtre si 60 secondes écoulées
        if current_time - self.rate_limiter['window_start'] >= 60:
            self.rate_limiter['requests_made'] = 0
            self.rate_limiter['window_start'] = current_time
            # Réduire progressivement le backoff si pas de 429 récents
            if self.rate_limiter['consecutive_429s'] == 0:
                self.rate_limiter['backoff_multiplier'] = max(1.0, self.rate_limiter['backoff_multiplier'] * 0.9)
        
        # Vérifier si on peut faire une requête
        if self.rate_limiter['requests_made'] >= self.rate_limiter['requests_per_minute']:
            wait_time = 60 - (current_time - self.rate_limiter['window_start'])
            if wait_time > 0:
                logger.info(f"⏳ Rate limit atteint, attente de {wait_time:.1f}s...")
                self.stats['total_wait_time'] += wait_time
                await asyncio.sleep(wait_time + 1)  # +1s de sécurité
                
                # Reset après attente
                self.rate_limiter['requests_made'] = 0
                self.rate_limiter['window_start'] = time.time()
        
        # Délai adaptatif basé sur les erreurs précédentes
        adaptive_delay = self.delay * self.rate_limiter['backoff_multiplier']
        if adaptive_delay > self.delay:
            logger.debug(f"⏱️ Délai adaptatif: {adaptive_delay:.2f}s (multiplier: {self.rate_limiter['backoff_multiplier']:.2f})")
        
        await asyncio.sleep(adaptive_delay)
        self.rate_limiter['requests_made'] += 1
    
    async def handle_rate_limit_error(self):
        """Gérer une erreur 429 (Too Many Requests)"""
        self.stats['rate_limit_hits'] += 1
        self.rate_limiter['consecutive_429s'] += 1
        
        # Augmenter le backoff de façon exponentielle mais limitée
        self.rate_limiter['backoff_multiplier'] = min(8.0, self.rate_limiter['backoff_multiplier'] * 1.5)
        
        # Attente progressive : plus on a de 429, plus on attend
        wait_time = min(120, 10 * self.rate_limiter['consecutive_429s'] + random.uniform(0, 5))
        
        logger.warning(f"🚨 Rate limit hit #{self.rate_limiter['consecutive_429s']}, attente {wait_time:.1f}s...")
        logger.info(f"📊 Nouveau multiplier de délai: {self.rate_limiter['backoff_multiplier']:.2f}")
        
        self.stats['total_wait_time'] += wait_time
        await asyncio.sleep(wait_time)
    
    def reset_rate_limit_success(self):
        """Réinitialiser les compteurs après un succès"""
        if self.rate_limiter['consecutive_429s'] > 0:
            logger.info(f"✅ Récupération du rate limiting après {self.rate_limiter['consecutive_429s']} erreurs")
            self.rate_limiter['consecutive_429s'] = 0
    
    async def start(self):
        """Démarrer la session HTTP"""
        connector = TCPConnector(
            limit=20,
            limit_per_host=10,
            ttl_dns_cache=300,
            use_dns_cache=True
        )
        
        self.session = ClientSession(
            connector=connector,
            timeout=aiohttp.ClientTimeout(total=10),
            headers={
                'User-Agent': 'RugCheck-Updater/1.0',
                'Accept': 'application/json'
            }
        )
        logger.info("🚀 Session HTTP démarrée")
        """Démarrer la session HTTP"""
        connector = TCPConnector(
            limit=20,
            limit_per_host=10,
            ttl_dns_cache=300,
            use_dns_cache=True
        )
        
        self.session = ClientSession(
            connector=connector,
            timeout=aiohttp.ClientTimeout(total=10),
            headers={
                'User-Agent': 'RugCheck-Updater/1.0',
                'Accept': 'application/json'
            }
        )
        logger.info("🚀 Session HTTP démarrée")
    
    async def stop(self):
        """Arrêter la session HTTP"""
        if self.session:
            await self.session.close()
        logger.info("🛑 Session HTTP fermée")
    
    def extract_rugcheck_score(self, rugcheck_data: dict) -> int:
        """
        Extraire le bon score depuis les données RugCheck
        
        Args:
            rugcheck_data: Données JSON de l'API RugCheck
            
        Returns:
            Score normalisé entre 0-100
        """
        if not rugcheck_data:
            return 50
        
        # Priorité 1: score_normalised (celui affiché sur le site)
        if "score_normalised" in rugcheck_data and rugcheck_data["score_normalised"] is not None:
            return max(0, min(100, int(rugcheck_data["score_normalised"])))
        
        # Priorité 2: calculer depuis les risques
        if "risks" in rugcheck_data and isinstance(rugcheck_data["risks"], list):
            total_risk = sum(risk.get("score", 0) for risk in rugcheck_data["risks"])
            calculated_score = max(0, 100 - total_risk)
            return calculated_score
        
        # Priorité 3: score brut (peut être > 100, donc on normalise)
        if "score" in rugcheck_data:
            raw_score = rugcheck_data["score"]
            return max(0, min(100, int(raw_score)))
        
        # Défaut
        return 50
    
    async def get_rugcheck_score(self, address: str) -> Optional[Dict]:
        """Récupérer le score RugCheck pour un token avec rate limiting robuste"""
        url = f"https://api.rugcheck.xyz/v1/tokens/{address}/report"
        
        # Attendre selon le rate limiting
        await self.wait_for_rate_limit()
        
        max_retries = 3
        for attempt in range(max_retries):
            try:
                async with self.session.get(url) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        
                        final_score = self.extract_rugcheck_score(data)
                        
                        # Réinitialiser les compteurs de rate limit en cas de succès
                        self.reset_rate_limit_success()
                        
                        return {
                            "rug_score": final_score,
                            "raw_score": data.get("score"),
                            "normalized_score": data.get("score_normalised"),
                            "has_data": True
                        }
                    
                    elif resp.status == 404:
                        logger.debug(f"Token {address} non trouvé sur RugCheck")
                        self.stats['no_data_found'] += 1
                        return None
                    
                    elif resp.status == 429:
                        logger.warning(f"Rate limit hit pour {address} (tentative {attempt + 1}/{max_retries})")
                        await self.handle_rate_limit_error()
                        
                        # Retry seulement si ce n'est pas la dernière tentative
                        if attempt < max_retries - 1:
                            continue
                        else:
                            self.stats['api_errors'] += 1
                            return None
                    
                    elif resp.status in [500, 502, 503, 504]:
                        # Erreurs serveur - retry avec délai
                        wait_time = (2 ** attempt) + random.uniform(0, 1)
                        logger.warning(f"Erreur serveur {resp.status} pour {address}, retry dans {wait_time:.1f}s")
                        await asyncio.sleep(wait_time)
                        
                        if attempt < max_retries - 1:
                            continue
                        else:
                            self.stats['api_errors'] += 1
                            return None
                    
                    else:
                        logger.debug(f"HTTP {resp.status} pour {address}")
                        self.stats['api_errors'] += 1
                        return None
                        
            except asyncio.TimeoutError:
                logger.debug(f"Timeout pour {address} (tentative {attempt + 1}/{max_retries})")
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 ** attempt)
                    continue
                else:
                    self.stats['api_errors'] += 1
                    return None
            except Exception as e:
                logger.debug(f"Erreur pour {address}: {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(1)
                    continue
                else:
                    self.stats['api_errors'] += 1
                    return None
        
        return None
    
    def get_tokens_to_update(self, limit: int = None, only_missing: bool = False) -> List[Tuple[str, str, Optional[int]]]:
        """
        Récupérer les tokens à mettre à jour
        
        Args:
            limit: Nombre maximum de tokens à récupérer
            only_missing: Si True, ne récupère que les tokens sans rug_score
            
        Returns:
            Liste de tuples (address, symbol, current_rug_score)
        """
        conn = sqlite3.connect(self.database_path)
        cursor = conn.cursor()
        
        try:
            if only_missing:
                query = '''
                    SELECT address, symbol, rug_score 
                    FROM tokens 
                    WHERE (rug_score IS NULL OR rug_score = 50)
                    AND symbol IS NOT NULL 
                    AND symbol != 'UNKNOWN'
                    ORDER BY first_discovered_at DESC
                '''
            else:
                query = '''
                    SELECT address, symbol, rug_score 
                    FROM tokens 
                    WHERE symbol IS NOT NULL 
                    AND symbol != 'UNKNOWN'
                    ORDER BY first_discovered_at DESC
                '''
            
            if limit:
                query += f" LIMIT {limit}"
            
            cursor.execute(query)
            return cursor.fetchall()
            
        except sqlite3.Error as e:
            logger.error(f"Erreur base de données: {e}")
            return []
        finally:
            conn.close()
    
    def update_token_rugcheck(self, address: str, new_rug_score: int, old_rug_score: Optional[int] = None) -> bool:
        """Mettre à jour le rug_score d'un token dans la table tokens"""
        conn = sqlite3.connect(self.database_path)
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                UPDATE tokens 
                SET rug_score = ?, updated_at = ?
                WHERE address = ?
            ''', (new_rug_score, datetime.now().strftime('%Y-%m-%d %H:%M:%S'), address))
            
            if cursor.rowcount > 0:
                conn.commit()
                
                # Stats
                if old_rug_score != new_rug_score:
                    self.stats['scores_changed'] += 1
                    logger.info(f"📊 {address}: {old_rug_score} → {new_rug_score}")
                else:
                    self.stats['scores_unchanged'] += 1
                
                return True
            else:
                logger.warning(f"Token {address} non trouvé en base")
                return False
                
        except sqlite3.Error as e:
            logger.error(f"Erreur mise à jour {address}: {e}")
            return False
        finally:
            conn.close()
    
    def update_tokens_hist_rugcheck(self, address: str, new_rug_score: int) -> int:
        """
        Mettre à jour le rug_score d'un token dans tous ses enregistrements tokens_hist
        
        Returns:
            Nombre d'enregistrements mis à jour
        """
        conn = sqlite3.connect(self.database_path)
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                UPDATE tokens_hist 
                SET rug_score = ?
                WHERE address = ?
            ''', (new_rug_score, address))
            
            updated_count = cursor.rowcount
            conn.commit()
            
            if updated_count > 0:
                logger.debug(f"📚 Mis à jour {updated_count} enregistrements historiques pour {address}")
            
            return updated_count
            
        except sqlite3.Error as e:
            logger.error(f"Erreur mise à jour historique {address}: {e}")
            return 0
        finally:
            conn.close()
    
    async def update_batch(self, tokens_batch: List[Tuple[str, str, Optional[int]]]) -> Dict:
        """Mettre à jour un batch de tokens"""
        batch_stats = {
            'processed': 0,
            'updated': 0,
            'errors': 0,
            'hist_updated': 0
        }
        
        for address, symbol, current_score in tokens_batch:
            try:
                logger.info(f"🔍 Traitement: {symbol} ({address[:8]}...)")
                
                # Récupérer le nouveau score
                rugcheck_data = await self.get_rugcheck_score(address)
                
                if rugcheck_data and rugcheck_data['has_data']:
                    new_score = rugcheck_data['rug_score']
                    
                    # Mettre à jour tokens
                    if self.update_token_rugcheck(address, new_score, current_score):
                        batch_stats['updated'] += 1
                        
                        # Mettre à jour tokens_hist
                        hist_count = self.update_tokens_hist_rugcheck(address, new_score)
                        batch_stats['hist_updated'] += hist_count
                        
                        logger.info(f"✅ {symbol}: score={new_score}, hist_records={hist_count}")
                    else:
                        batch_stats['errors'] += 1
                else:
                    logger.debug(f"❌ Pas de données RugCheck pour {symbol}")
                    batch_stats['errors'] += 1
                
                batch_stats['processed'] += 1
                self.stats['total_processed'] += 1
                
                # Délai entre requêtes (maintenant géré par wait_for_rate_limit)
                # Le délai est automatiquement ajusté selon les rate limits
                
            except Exception as e:
                logger.error(f"Erreur traitement {symbol}: {e}")
                batch_stats['errors'] += 1
                continue
        
        return batch_stats
    
    async def run_update(self, limit: int = None, only_missing: bool = False, update_history: bool = True):
        """
        Lancer la mise à jour des scores RugCheck
        
        Args:
            limit: Nombre maximum de tokens à traiter
            only_missing: Si True, ne traite que les tokens sans rug_score
            update_history: Si True, met aussi à jour tokens_hist
        """
        await self.start()
        
        try:
            logger.info("🛡️ Démarrage de la mise à jour des scores RugCheck")
            logger.info(f"📋 Paramètres: limit={limit}, only_missing={only_missing}, update_history={update_history}")
            
            # Récupérer les tokens à traiter
            tokens_to_update = self.get_tokens_to_update(limit, only_missing)
            
            if not tokens_to_update:
                logger.info("✅ Aucun token à mettre à jour")
                return
            
            logger.info(f"📊 {len(tokens_to_update)} tokens à traiter")
            
            # Traiter par batches
            total_hist_updated = 0
            
            for i in range(0, len(tokens_to_update), self.batch_size):
                batch = tokens_to_update[i:i + self.batch_size]
                batch_num = (i // self.batch_size) + 1
                total_batches = (len(tokens_to_update) + self.batch_size - 1) // self.batch_size
                
                logger.info(f"📦 Batch {batch_num}/{total_batches} ({len(batch)} tokens)")
                
                batch_stats = await self.update_batch(batch)
                total_hist_updated += batch_stats['hist_updated']
                
                logger.info(f"📊 Batch {batch_num} terminé: {batch_stats['updated']}/{batch_stats['processed']} succès")
                
                # Petit délai entre batches
                if i + self.batch_size < len(tokens_to_update):
                    await asyncio.sleep(2)
            
            # Stats finales
            self.stats['successful_updates'] = self.stats['scores_changed'] + self.stats['scores_unchanged']
            
            logger.info("=" * 60)
            logger.info("📊 RÉSUMÉ FINAL")
            logger.info("=" * 60)
            logger.info(f"✅ Tokens traités: {self.stats['total_processed']}")
            logger.info(f"💾 Mises à jour réussies: {self.stats['successful_updates']}")
            logger.info(f"🔄 Scores modifiés: {self.stats['scores_changed']}")
            logger.info(f"⚪ Scores inchangés: {self.stats['scores_unchanged']}")
            logger.info(f"📚 Enregistrements historiques mis à jour: {total_hist_updated}")
            logger.info(f"❌ Erreurs API: {self.stats['api_errors']}")
            logger.info(f"🚫 Tokens sans données: {self.stats['no_data_found']}")
            logger.info(f"🚨 Rate limits rencontrés: {self.stats['rate_limit_hits']}")
            logger.info(f"⏱️ Temps d'attente total: {self.stats['total_wait_time']:.1f}s")
            
            if self.stats['total_wait_time'] > 0:
                effective_rate = self.stats['total_processed'] / (self.stats['total_wait_time'] / 60) if self.stats['total_wait_time'] > 0 else 0
                logger.info(f"📈 Débit effectif: {effective_rate:.1f} tokens/min")
            
            logger.info("=" * 60)
            
        except Exception as e:
            logger.error(f"Erreur globale: {e}")
        finally:
            await self.stop()

def main():
    """Fonction principale"""
    parser = argparse.ArgumentParser(description="🛡️ Mise à jour des scores RugCheck")
    
    parser.add_argument("--database", default="tokens.db", help="Chemin de la base de données")
    parser.add_argument("--limit", type=int, help="Nombre maximum de tokens à traiter")
    parser.add_argument("--batch-size", type=int, default=5, help="Taille des batches (défaut: 5)")
    parser.add_argument("--delay", type=float, default=2.0, help="Délai entre requêtes (secondes, défaut: 2.0)")
    parser.add_argument("--requests-per-minute", type=int, default=30, help="Limite de requêtes par minute (défaut: 30)")
    parser.add_argument("--only-missing", action="store_true", help="Ne traiter que les tokens sans rug_score")
    parser.add_argument("--no-history", action="store_true", help="Ne pas mettre à jour tokens_hist")
    parser.add_argument("--dry-run", action="store_true", help="Simulation sans mise à jour")
    
    args = parser.parse_args()
    
    if args.dry_run:
        logger.info("🧪 MODE SIMULATION - Aucune mise à jour ne sera effectuée")
        return
    
    # Confirmation pour mise à jour complète
    if not args.only_missing and not args.limit:
        response = input("⚠️ Vous allez mettre à jour TOUS les tokens. Continuer? (y/N): ")
        if response.lower() != 'y':
            logger.info("❌ Annulé par l'utilisateur")
            return
    
    updater = RugCheckUpdater(
        database_path=args.database,
        batch_size=args.batch_size,
        delay=args.delay
    )
    
    # Ajuster la limite de requêtes par minute
    updater.rate_limiter['requests_per_minute'] = args.requests_per_minute
    
    try:
        asyncio.run(updater.run_update(
            limit=args.limit,
            only_missing=args.only_missing,
            update_history=not args.no_history
        ))
    except KeyboardInterrupt:
        logger.info("\n🛑 Arrêt demandé par l'utilisateur")
    except Exception as e:
        logger.error(f"❌ Erreur fatale: {e}")

if __name__ == "__main__":
    main()