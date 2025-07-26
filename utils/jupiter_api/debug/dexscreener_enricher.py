#!/usr/bin/env python3
"""
📈 DexScreener Data Enricher
Récupère toutes les données DexScreener et remplit les colonnes dexscreener_* de la table tokens
Respecte le rate limit de DexScreener (300 requêtes par minute)
"""

import sqlite3
import requests
import json
import time
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple
import argparse
from dataclasses import dataclass

# Configuration du logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

@dataclass
class RateLimiter:
    """Rate limiter pour DexScreener API"""
    requests_per_minute: int = 300  # Limite DexScreener
    requests_made: int = 0
    window_start: float = 0
    
    def __post_init__(self):
        self.window_start = time.time()
    
    def can_make_request(self) -> bool:
        """Vérifier si on peut faire une requête"""
        current_time = time.time()
        
        # Reset window si 60 secondes écoulées
        if current_time - self.window_start >= 60:
            self.requests_made = 0
            self.window_start = current_time
        
        return self.requests_made < self.requests_per_minute
    
    def wait_if_needed(self):
        """Attendre si nécessaire pour respecter le rate limit"""
        if not self.can_make_request():
            wait_time = 60 - (time.time() - self.window_start)
            if wait_time > 0:
                logger.info(f"⏳ Rate limit atteint, attente de {wait_time:.1f}s...")
                time.sleep(wait_time + 0.1)  # Petit buffer
                self.requests_made = 0
                self.window_start = time.time()
    
    def record_request(self):
        """Enregistrer qu'une requête a été faite"""
        self.requests_made += 1

class DexScreenerEnricher:
    """Enrichisseur de données DexScreener"""
    
    def __init__(self, database_path: str = "../tokens.db"):
        self.database_path = database_path
        self.rate_limiter = RateLimiter()
        self.base_url = "https://api.dexscreener.com/latest/dex/tokens"
        
        # Statistiques
        self.stats = {
            'total_processed': 0,
            'successful_updates': 0,
            'api_errors': 0,
            'no_data_found': 0,
            'database_errors': 0
        }
    
    def get_tokens_to_enrich(self, limit: int, strategy: str = "oldest", min_hours_since_update: int = 1) -> List[Dict]:
        """
        Récupérer les tokens à enrichir selon différentes stratégies
        Exclut automatiquement les tokens mis à jour récemment
        
        Args:
            limit: Nombre de tokens à récupérer
            strategy: 'oldest', 'never_updated', 'recent', 'random', 'force_all'
            min_hours_since_update: Heures minimum depuis la dernière MAJ DexScreener
        """
        conn = sqlite3.connect(self.database_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        try:
            # Condition commune pour exclure les tokens récemment mis à jour
            if strategy == "force_all":
                # Force l'enrichissement même des tokens récemment mis à jour
                exclude_recent_condition = ""
                exclude_recent_params = ()
            else:
                exclude_recent_condition = '''
                    AND (dexscreener_last_dexscreener_update IS NULL 
                         OR dexscreener_last_dexscreener_update = ''
                         OR dexscreener_last_dexscreener_update < datetime('now', '-{} hours', 'localtime'))
                '''.format(min_hours_since_update)
                exclude_recent_params = ()
            
            if strategy == "never_updated":
                # Tokens jamais mis à jour avec DexScreener
                query = f'''
                    SELECT address, symbol, updated_at, dexscreener_last_dexscreener_update
                    FROM tokens 
                    WHERE (dexscreener_last_dexscreener_update IS NULL 
                           OR dexscreener_last_dexscreener_update = '')
                    AND symbol IS NOT NULL 
                    AND symbol != 'UNKNOWN' 
                    AND symbol != ''
                    ORDER BY first_discovered_at DESC
                    LIMIT ?
                '''
                params = (limit,)
                
            elif strategy == "oldest":
                # Tokens avec les données DexScreener les plus anciennes (en excluant les récents)
                query = f'''
                    SELECT address, symbol, updated_at, dexscreener_last_dexscreener_update
                    FROM tokens 
                    WHERE symbol IS NOT NULL 
                    AND symbol != 'UNKNOWN' 
                    AND symbol != ''
                    {exclude_recent_condition}
                    ORDER BY COALESCE(dexscreener_last_dexscreener_update, '1970-01-01') ASC
                    LIMIT ?
                '''
                params = (limit,)
                
            elif strategy == "recent":
                # Tokens récemment découverts (mais pas récemment mis à jour DexScreener)
                query = f'''
                    SELECT address, symbol, updated_at, dexscreener_last_dexscreener_update
                    FROM tokens 
                    WHERE first_discovered_at > datetime('now', '-24 hours', 'localtime')
                    AND symbol IS NOT NULL 
                    AND symbol != 'UNKNOWN' 
                    AND symbol != ''
                    {exclude_recent_condition}
                    ORDER BY first_discovered_at DESC
                    LIMIT ?
                '''
                params = (limit,)
                
            elif strategy == "random":
                # Sélection aléatoire (en excluant les récents)
                query = f'''
                    SELECT address, symbol, updated_at, dexscreener_last_dexscreener_update
                    FROM tokens 
                    WHERE symbol IS NOT NULL 
                    AND symbol != 'UNKNOWN' 
                    AND symbol != ''
                    {exclude_recent_condition}
                    ORDER BY RANDOM()
                    LIMIT ?
                '''
                params = (limit,)
                
            elif strategy == "force_all":
                # Force l'enrichissement de tous les tokens (ignore les MAJ récentes)
                query = '''
                    SELECT address, symbol, updated_at, dexscreener_last_dexscreener_update
                    FROM tokens 
                    WHERE symbol IS NOT NULL 
                    AND symbol != 'UNKNOWN' 
                    AND symbol != ''
                    ORDER BY COALESCE(dexscreener_last_dexscreener_update, '1970-01-01') ASC
                    LIMIT ?
                '''
                params = (limit,)
                
            else:
                raise ValueError(f"Stratégie inconnue: {strategy}")
            
            cursor.execute(query, params)
            tokens = [dict(row) for row in cursor.fetchall()]
            
            # Afficher des informations sur la sélection
            if strategy != "force_all":
                # Compter combien de tokens ont été exclus à cause de MAJ récentes
                cursor.execute('''
                    SELECT COUNT(*) FROM tokens 
                    WHERE symbol IS NOT NULL 
                    AND symbol != 'UNKNOWN' 
                    AND symbol != ''
                    AND dexscreener_last_dexscreener_update IS NOT NULL
                    AND dexscreener_last_dexscreener_update != ''
                    AND dexscreener_last_dexscreener_update >= datetime('now', '-{} hours', 'localtime')
                '''.format(min_hours_since_update))
                
                excluded_count = cursor.fetchone()[0]
                
                if excluded_count > 0:
                    logger.info(f"⏭️  {excluded_count} tokens exclus (mis à jour DexScreener < {min_hours_since_update}h)")
            
            logger.info(f"📋 {len(tokens)} tokens sélectionnés avec stratégie '{strategy}'")
            
            # Afficher quelques exemples des tokens sélectionnés
            if tokens:
                logger.info("📝 Exemples de tokens sélectionnés:")
                for i, token in enumerate(tokens[:3]):
                    last_update = token.get('dexscreener_last_dexscreener_update', 'Jamais')
                    if last_update and last_update != 'Jamais':
                        try:
                            from datetime import datetime
                            last_dt = datetime.strptime(last_update, '%Y-%m-%d %H:%M:%S')
                            hours_ago = (datetime.now() - last_dt).total_seconds() / 3600
                            last_update_str = f"il y a {hours_ago:.1f}h"
                        except:
                            last_update_str = last_update
                    else:
                        last_update_str = "Jamais"
                    
                    logger.info(f"   {i+1}. {token.get('symbol', 'UNKNOWN')} - Dernière MAJ DS: {last_update_str}")
            
            return tokens
            
        except sqlite3.Error as e:
            logger.error(f"Erreur base de données: {e}")
            return []
        finally:
            conn.close()
    
    def fetch_dexscreener_data(self, address: str) -> Optional[Dict]:
        """
        Récupérer les données DexScreener pour un token
        
        Returns:
            Dict contenant toutes les données DexScreener ou None si erreur
        """
        self.rate_limiter.wait_if_needed()
        
        url = f"{self.base_url}/{address}"
        
        try:
            response = requests.get(url, timeout=10)
            self.rate_limiter.record_request()
            
            if response.status_code == 200:
                data = response.json()
                
                if data.get('pairs') and len(data['pairs']) > 0:
                    # Prendre la paire avec le plus de liquidité
                    best_pair = max(
                        data['pairs'], 
                        key=lambda p: float(p.get('liquidity', {}).get('usd', 0) or 0)
                    )
                    return best_pair
                else:
                    logger.debug(f"Aucune paire trouvée pour {address}")
                    self.stats['no_data_found'] += 1
                    return None
                    
            elif response.status_code == 429:
                logger.warning(f"Rate limit hit pour {address}")
                time.sleep(2)
                return None
            else:
                logger.warning(f"API DexScreener error {response.status_code} pour {address}")
                self.stats['api_errors'] += 1
                return None
                
        except Exception as e:
            logger.error(f"Erreur récupération DexScreener pour {address}: {e}")
            self.stats['api_errors'] += 1
            return None
    
    def extract_dexscreener_fields(self, pair_data: Dict) -> Dict:
        """
        Extraire tous les champs DexScreener selon votre structure de table
        
        Args:
            pair_data: Données de la paire depuis l'API DexScreener
            
        Returns:
            Dict avec les valeurs pour toutes les colonnes dexscreener_*
        """
        def safe_float(value, default=0.0):
            """Conversion sécurisée en float"""
            try:
                return float(value) if value is not None else default
            except (ValueError, TypeError):
                return default
        
        def safe_int(value, default=0):
            """Conversion sécurisée en int"""
            try:
                return int(value) if value is not None else default
            except (ValueError, TypeError):
                return default
        
        # Extraire toutes les données selon votre structure
        extracted = {
            # Date de création de la paire
            'dexscreener_pair_created_at': None,
            
            # Prix et market cap
            'dexscreener_price_usd': safe_float(pair_data.get('priceUsd')),
            'dexscreener_market_cap': safe_float(pair_data.get('marketCap')),
            
            # Liquidités
            'dexscreener_liquidity_base': safe_float(pair_data.get('liquidity', {}).get('base')),
            'dexscreener_liquidity_quote': safe_float(pair_data.get('liquidity', {}).get('usd')),
            
            # Volumes
            'dexscreener_volume_1h': safe_float(pair_data.get('volume', {}).get('h1')),
            'dexscreener_volume_6h': safe_float(pair_data.get('volume', {}).get('h6')),
            'dexscreener_volume_24h': safe_float(pair_data.get('volume', {}).get('h24')),
            
            # Changements de prix
            'dexscreener_price_change_1h': safe_float(pair_data.get('priceChange', {}).get('h1')),
            'dexscreener_price_change_6h': safe_float(pair_data.get('priceChange', {}).get('h6')),
            'dexscreener_price_change_h24': safe_float(pair_data.get('priceChange', {}).get('h24')),
            
            # Transactions
            'dexscreener_txns_1h': 0,
            'dexscreener_txns_6h': 0,
            'dexscreener_txns_24h': 0,
            'dexscreener_buys_1h': 0,
            'dexscreener_sells_1h': 0,
            'dexscreener_buys_24h': 0,
            'dexscreener_sells_24h': 0,
            
            # URL et timestamp de mise à jour
            'dexscreener_dexscreener_url': pair_data.get('url', ''),
            'dexscreener_last_dexscreener_update': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }
        
        # Traitement spécial pour la date de création
        if 'pairCreatedAt' in pair_data and pair_data['pairCreatedAt']:
            try:
                # Convertir timestamp milliseconds en datetime
                timestamp_ms = pair_data['pairCreatedAt']
                created_datetime = datetime.fromtimestamp(timestamp_ms / 1000)
                extracted['dexscreener_pair_created_at'] = created_datetime.strftime('%Y-%m-%d %H:%M:%S')
            except (ValueError, TypeError) as e:
                logger.debug(f"Erreur conversion date: {e}")
        
        # Traitement des transactions (si disponibles)
        txns = pair_data.get('txns', {})
        
        for period in ['h1', 'h6', 'h24']:
            period_data = txns.get(period, {})
            
            buys = safe_int(period_data.get('buys'))
            sells = safe_int(period_data.get('sells'))
            total = buys + sells
            
            # Mapping des périodes vers les noms de colonnes
            if period == 'h1':
                extracted['dexscreener_txns_1h'] = total
                extracted['dexscreener_buys_1h'] = buys
                extracted['dexscreener_sells_1h'] = sells
            elif period == 'h6':
                extracted['dexscreener_txns_6h'] = total
            elif period == 'h24':
                extracted['dexscreener_txns_24h'] = total
                extracted['dexscreener_buys_24h'] = buys
                extracted['dexscreener_sells_24h'] = sells
        
        return extracted
    
    def update_token_in_database(self, address: str, dexscreener_data: Dict) -> bool:
        """
        Mettre à jour un token dans la base de données avec les données DexScreener
        
        Args:
            address: Adresse du token
            dexscreener_data: Données extraites de DexScreener
            
        Returns:
            True si succès, False sinon
        """
        conn = sqlite3.connect(self.database_path)
        cursor = conn.cursor()
        
        try:
            # Construire la requête UPDATE avec tous les champs DexScreener
            update_query = '''
                UPDATE tokens SET 
                    dexscreener_pair_created_at = ?,
                    dexscreener_price_usd = ?,
                    dexscreener_market_cap = ?,
                    dexscreener_liquidity_base = ?,
                    dexscreener_liquidity_quote = ?,
                    dexscreener_volume_1h = ?,
                    dexscreener_volume_6h = ?,
                    dexscreener_volume_24h = ?,
                    dexscreener_price_change_1h = ?,
                    dexscreener_price_change_6h = ?,
                    dexscreener_price_change_h24 = ?,
                    dexscreener_txns_1h = ?,
                    dexscreener_txns_6h = ?,
                    dexscreener_txns_24h = ?,
                    dexscreener_buys_1h = ?,
                    dexscreener_sells_1h = ?,
                    dexscreener_buys_24h = ?,
                    dexscreener_sells_24h = ?,
                    dexscreener_dexscreener_url = ?,
                    dexscreener_last_dexscreener_update = ?,
                    updated_at = ?
                WHERE address = ?
            '''
            
            # Préparer les valeurs
            values = (
                dexscreener_data.get('dexscreener_pair_created_at'),
                dexscreener_data.get('dexscreener_price_usd'),
                dexscreener_data.get('dexscreener_market_cap'),
                dexscreener_data.get('dexscreener_liquidity_base'),
                dexscreener_data.get('dexscreener_liquidity_quote'),
                dexscreener_data.get('dexscreener_volume_1h'),
                dexscreener_data.get('dexscreener_volume_6h'),
                dexscreener_data.get('dexscreener_volume_24h'),
                dexscreener_data.get('dexscreener_price_change_1h'),
                dexscreener_data.get('dexscreener_price_change_6h'),
                dexscreener_data.get('dexscreener_price_change_h24'),
                dexscreener_data.get('dexscreener_txns_1h'),
                dexscreener_data.get('dexscreener_txns_6h'),
                dexscreener_data.get('dexscreener_txns_24h'),
                dexscreener_data.get('dexscreener_buys_1h'),
                dexscreener_data.get('dexscreener_sells_1h'),
                dexscreener_data.get('dexscreener_buys_24h'),
                dexscreener_data.get('dexscreener_sells_24h'),
                dexscreener_data.get('dexscreener_dexscreener_url'),
                dexscreener_data.get('dexscreener_last_dexscreener_update'),
                datetime.now().strftime('%Y-%m-%d %H:%M:%S'),  # updated_at
                address
            )
            
            cursor.execute(update_query, values)
            
            if cursor.rowcount > 0:
                conn.commit()
                logger.debug(f"✅ Token {address} mis à jour avec succès")
                return True
            else:
                logger.warning(f"⚠️ Token {address} non trouvé dans la base")
                return False
                
        except sqlite3.Error as e:
            logger.error(f"Erreur base de données pour {address}: {e}")
            self.stats['database_errors'] += 1
            conn.rollback()
            return False
        finally:
            conn.close()
    
    def enrich_token(self, token: Dict) -> bool:
        """
        Enrichir un token avec les données DexScreener
        
        Args:
            token: Dict contenant au minimum 'address' et 'symbol'
            
        Returns:
            True si succès, False sinon
        """
        address = token['address']
        symbol = token.get('symbol', 'UNKNOWN')
        
        logger.info(f"🔍 Enrichissement DexScreener: {symbol} ({address[:8]}...)")
        
        # Récupérer les données DexScreener
        pair_data = self.fetch_dexscreener_data(address)
        
        if not pair_data:
            logger.info(f"⚪ {symbol}: Aucune donnée DexScreener trouvée")
            return False
        
        # Extraire les champs selon votre structure
        dexscreener_fields = self.extract_dexscreener_fields(pair_data)
        
        # Mettre à jour en base
        success = self.update_token_in_database(address, dexscreener_fields)
        
        if success:
            self.stats['successful_updates'] += 1
            
            # Log des informations clés
            price = dexscreener_fields.get('dexscreener_price_usd', 0)
            volume_24h = dexscreener_fields.get('dexscreener_volume_24h', 0)
            liquidity = dexscreener_fields.get('dexscreener_liquidity_quote', 0)
            
            logger.info(f"✅ {symbol}: Prix=${price:.8f}, Vol24h=${volume_24h:,.0f}, Liq=${liquidity:,.0f}")
        
        return success
    
    def run_enrichment(self, limit: int, strategy: str = "oldest", delay: float = 0.2, min_hours_since_update: int = 1) -> Dict:
        """
        Lancer l'enrichissement DexScreener
        
        Args:
            limit: Nombre de tokens à enrichir
            strategy: Stratégie de sélection des tokens
            delay: Délai entre chaque requête (secondes)
            min_hours_since_update: Heures minimum depuis la dernière MAJ DexScreener
            
        Returns:
            Dict avec les statistiques d'enrichissement
        """
        start_time = time.time()
        
        logger.info("=" * 80)
        logger.info("📈 DÉMARRAGE ENRICHISSEMENT DEXSCREENER")
        logger.info("=" * 80)
        logger.info(f"🎯 Stratégie: {strategy}")
        logger.info(f"📊 Tokens à traiter: {limit}")
        logger.info(f"⏱️  Délai entre requêtes: {delay}s")
        logger.info(f"🚦 Rate limit: {self.rate_limiter.requests_per_minute} req/min")
        
        if strategy != "force_all":
            logger.info(f"⏭️  Exclusion tokens MAJ DexScreener < {min_hours_since_update}h")
        else:
            logger.info("🔄 Mode FORCE: Inclut les tokens récemment mis à jour")
        
        # Récupérer les tokens à enrichir
        tokens = self.get_tokens_to_enrich(limit, strategy, min_hours_since_update)
        
        if not tokens:
            logger.warning("⚠️  Aucun token à enrichir trouvé avec ces critères")
            logger.info("💡 Suggestions:")
            logger.info("   - Augmentez --limit")
            logger.info("   - Changez de --strategy")
            logger.info("   - Réduisez --min-hours-since-update")
            logger.info("   - Utilisez --strategy force_all pour ignorer les MAJ récentes")
            return {'success': False, 'message': 'Aucun token trouvé'}
        
        logger.info(f"📋 {len(tokens)} tokens sélectionnés pour enrichissement")
        logger.info("=" * 50)
        
        # Enrichir chaque token
        for i, token in enumerate(tokens, 1):
            logger.info(f"\n[{i}/{len(tokens)}] " + "="*40)
            
            success = self.enrich_token(token)
            self.stats['total_processed'] += 1
            
            # Délai entre les requêtes (en plus du rate limiter)
            if i < len(tokens) and delay > 0:
                time.sleep(delay)
        
        # Rapport final
        elapsed_time = time.time() - start_time
        
        logger.info("\n" + "="*80)
        logger.info("📋 RAPPORT FINAL ENRICHISSEMENT DEXSCREENER")
        logger.info("="*80)
        logger.info(f"⏱️  Durée totale:          {elapsed_time:.1f}s")
        logger.info(f"📊 Tokens traités:        {self.stats['total_processed']}")
        logger.info(f"✅ Mises à jour réussies: {self.stats['successful_updates']}")
        logger.info(f"⚪ Aucune donnée trouvée: {self.stats['no_data_found']}")
        logger.info(f"❌ Erreurs API:           {self.stats['api_errors']}")
        logger.info(f"💾 Erreurs base:          {self.stats['database_errors']}")
        
        success_rate = (self.stats['successful_updates'] / self.stats['total_processed'] * 100) if self.stats['total_processed'] > 0 else 0
        logger.info(f"📈 Taux de succès:        {success_rate:.1f}%")
        
        if self.stats['successful_updates'] > 0:
            avg_time_per_token = elapsed_time / self.stats['total_processed']
            logger.info(f"⚡ Temps moyen/token:     {avg_time_per_token:.2f}s")
            
            tokens_per_hour = 3600 / avg_time_per_token if avg_time_per_token > 0 else 0
            logger.info(f"🚀 Débit estimé:          {tokens_per_hour:.0f} tokens/heure")
        
        logger.info(f"🌐 Requêtes API utilisées: {self.rate_limiter.requests_made}")
        
        # Conseil pour le prochain lancement
        if self.stats['successful_updates'] > 0:
            logger.info("\n💡 CONSEIL POUR LE PROCHAIN LANCEMENT:")
            logger.info(f"   Les tokens enrichis sont exclus par défaut pendant {min_hours_since_update}h")
            logger.info("   Pour forcer leur mise à jour, utilisez --strategy force_all")
        
        logger.info("="*80)
        
        return {
            'success': True,
            'stats': self.stats,
            'elapsed_time': elapsed_time,
            'success_rate': success_rate
        }

def main():
    """Fonction principale"""
    parser = argparse.ArgumentParser(description="DexScreener Data Enricher")
    
    parser.add_argument("--database", default="../tokens.db", help="Chemin vers la base de données")
    parser.add_argument("--limit", type=int, default=50, help="Nombre de tokens à enrichir")
    parser.add_argument("--strategy", choices=['oldest', 'never_updated', 'recent', 'random', 'force_all'], 
                       default='oldest', help="Stratégie de sélection des tokens")
    parser.add_argument("--delay", type=float, default=0.2, help="Délai entre requêtes (secondes)")
    parser.add_argument("--min-hours-since-update", type=int, default=1, 
                       help="Heures minimum depuis dernière MAJ DexScreener (0 pour désactiver)")
    parser.add_argument("--verbose", action="store_true", help="Mode verbose")
    parser.add_argument("--dry-run", action="store_true", help="Simulation sans mise à jour")
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    if args.dry_run:
        logger.info("🧪 MODE SIMULATION - Aucune modification en base")
    
    # Créer l'enrichisseur
    enricher = DexScreenerEnricher(args.database)
    
    try:
        if args.dry_run:
            # Mode simulation
            tokens = enricher.get_tokens_to_enrich(args.limit, args.strategy, args.min_hours_since_update)
            logger.info(f"📋 Simulation: {len(tokens)} tokens seraient enrichis")
            for i, token in enumerate(tokens[:5], 1):  # Afficher les 5 premiers
                last_update = token.get('dexscreener_last_dexscreener_update', 'Jamais')
                logger.info(f"   {i}. {token.get('symbol', 'UNKNOWN')} ({token['address'][:8]}...) - Dernière MAJ: {last_update}")
            if len(tokens) > 5:
                logger.info(f"   ... et {len(tokens) - 5} autres")
        else:
            # Enrichissement réel
            results = enricher.run_enrichment(
                limit=args.limit,
                strategy=args.strategy,
                delay=args.delay,
                min_hours_since_update=args.min_hours_since_update
            )
            
            if results['success']:
                logger.info("🎯 Enrichissement terminé avec succès!")
                return 0
            else:
                logger.error("❌ Enrichissement échoué")
                return 1
                
    except KeyboardInterrupt:
        logger.info("\n🛑 Enrichissement interrompu par l'utilisateur")
        return 1
    except Exception as e:
        logger.error(f"❌ Erreur lors de l'enrichissement: {e}")
        return 1

if __name__ == "__main__":
    exit(main())