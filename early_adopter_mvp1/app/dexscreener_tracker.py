#!/usr/bin/env python3
"""
DexScreener Token Tracker
Surveille 4 endpoints DexScreener et stocke les données dans SQLite
"""

import sqlite3
import requests
import json
import time
import logging
from datetime import datetime
from typing import Dict, List, Optional, Tuple
import argparse
from urllib.parse import urlparse

class DexScreenerTracker:
    def __init__(self, db_path: str = "dexscreener.db", debug: bool = False):
        self.db_path = db_path
        self.debug = debug
        
        # Statistiques cumulées
        self.cumulative_stats = {
            "total_created": 0,
            "total_updated": 0,
            "cycles_completed": 0,
            "start_time": datetime.now()
        }
        
        # Configuration des endpoints
        self.endpoints = {
            "latest_profiles": "https://api.dexscreener.com/token-profiles/latest/v1",
            "top_boosts": "https://api.dexscreener.com/token-boosts/top/v1", 
            "latest_boosts": "https://api.dexscreener.com/token-boosts/latest/v1",
            "search_pumpfun": "https://api.dexscreener.com/latest/dex/search/?q=pumpfun+solana"
        }
        
        # Configuration du logging
        log_level = logging.DEBUG if debug else logging.INFO
        
        # Configuration pour gérer l'encodage sur Windows
        file_handler = logging.FileHandler('dexscreener_tracker.log', encoding='utf-8')
        console_handler = logging.StreamHandler()
        
        # Format du logging
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        file_handler.setFormatter(formatter)
        console_handler.setFormatter(formatter)
        
        logging.basicConfig(
            level=log_level,
            handlers=[file_handler, console_handler]
        )
        self.logger = logging.getLogger(__name__)
        
        # Initialisation de la base de données
        self._init_database()
        
    def _init_database(self):
        """Initialise la base de données SQLite avec la structure complète"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # Création de la table principale avec toutes les colonnes détaillées
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS tokens (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    
                    -- Identifiants principaux
                    token_address TEXT UNIQUE NOT NULL,
                    chain_id TEXT,
                    dex_id TEXT,
                    url TEXT,
                    pair_address TEXT,
                    
                    -- Informations du token de base
                    base_token_address TEXT,
                    base_token_name TEXT,
                    base_token_symbol TEXT,
                    
                    -- Informations du token de cotation
                    quote_token_address TEXT,
                    quote_token_name TEXT,
                    quote_token_symbol TEXT,
                    
                    -- Prix
                    price_native TEXT,
                    price_usd TEXT,
                    
                    -- Transactions (m5)
                    txns_m5_buys INTEGER,
                    txns_m5_sells INTEGER,
                    
                    -- Transactions (h1)
                    txns_h1_buys INTEGER,
                    txns_h1_sells INTEGER,
                    
                    -- Transactions (h6)
                    txns_h6_buys INTEGER,
                    txns_h6_sells INTEGER,
                    
                    -- Transactions (h24)
                    txns_h24_buys INTEGER,
                    txns_h24_sells INTEGER,
                    
                    -- Volume
                    volume_m5 REAL,
                    volume_h1 REAL,
                    volume_h6 REAL,
                    volume_h24 REAL,
                    
                    -- Changement de prix
                    price_change_m5 REAL,
                    price_change_h1 REAL,
                    price_change_h6 REAL,
                    price_change_h24 REAL,
                    
                    -- Liquidité
                    liquidity_usd REAL,
                    liquidity_base REAL,
                    liquidity_quote REAL,
                    
                    -- Métriques financières
                    fdv REAL,
                    market_cap REAL,
                    pair_created_at INTEGER,
                    
                    -- Images et médias
                    icon TEXT,
                    header TEXT,
                    open_graph TEXT,
                    image_url TEXT,
                    info_header TEXT,
                    info_open_graph TEXT,
                    
                    -- Informations textuelles
                    description TEXT,
                    
                    -- Liens sociaux et web (JSON stringifiés)
                    links TEXT,
                    info_websites TEXT,
                    info_socials TEXT,
                    
                    -- Boosts
                    total_amount INTEGER,
                    amount INTEGER,
                    boosts_active INTEGER,
                    
                    -- Métadonnées
                    created_by_endpoint TEXT NOT NULL,
                    updated_by_endpoint TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Table pour les statistiques cumulées
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS stats_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    endpoint_name TEXT,
                    items_processed INTEGER,
                    items_created INTEGER,
                    items_updated INTEGER,
                    cycle_number INTEGER
                )
            ''')
            
            # Index pour améliorer les performances
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_token_address ON tokens(token_address)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_chain_id ON tokens(chain_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_created_by_endpoint ON tokens(created_by_endpoint)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_pair_address ON tokens(pair_address)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_base_token_symbol ON tokens(base_token_symbol)')
            
            conn.commit()
            self.logger.info("Base de données initialisée avec succès")

    def _make_request(self, endpoint_name: str, url: str) -> Optional[Dict]:
        """Effectue une requête HTTP vers l'endpoint spécifié"""
        try:
            self.logger.debug(f"Requête vers {endpoint_name}: {url}")
            response = requests.get(url, timeout=30)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            self.logger.error(f"Erreur lors de la requête {endpoint_name}: {e}")
            return None
        except json.JSONDecodeError as e:
            self.logger.error(f"Erreur de décodage JSON pour {endpoint_name}: {e}")
            return None

    def _extract_token_address(self, item: Dict, endpoint_name: str) -> Optional[str]:
        """Extrait l'adresse du token selon le type d'endpoint"""
        if endpoint_name == "search_pumpfun":
            # Pour l'endpoint de recherche, on utilise l'adresse du base token
            base_token = item.get("baseToken", {})
            return base_token.get("address")
        else:
            # Pour les autres endpoints, on utilise tokenAddress
            return item.get("tokenAddress")

    def _prepare_token_data(self, item: Dict, endpoint_name: str) -> Dict:
        """Prépare les données du token pour l'insertion/mise à jour"""
        token_address = self._extract_token_address(item, endpoint_name)
        
        data = {
            "token_address": token_address,
            "chain_id": item.get("chainId"),
            "url": item.get("url"),
            "icon": item.get("icon"),
            "header": item.get("header"),
            "open_graph": item.get("openGraph"),
            "description": item.get("description"),
            "links": json.dumps(item.get("links", [])) if item.get("links") else None,
            "total_amount": item.get("totalAmount"),
            "amount": item.get("amount"),
        }
        
        # Données spécifiques aux paires (endpoint search)
        if endpoint_name == "search_pumpfun":
            base_token = item.get("baseToken", {})
            quote_token = item.get("quoteToken", {})
            txns = item.get("txns", {})
            volume = item.get("volume", {})
            price_change = item.get("priceChange", {})
            liquidity = item.get("liquidity", {})
            info = item.get("info", {})
            boosts = item.get("boosts", {})
            
            data.update({
                "dex_id": item.get("dexId"),
                "pair_address": item.get("pairAddress"),
                
                # Base token
                "base_token_address": base_token.get("address"),
                "base_token_name": base_token.get("name"),
                "base_token_symbol": base_token.get("symbol"),
                
                # Quote token
                "quote_token_address": quote_token.get("address"),
                "quote_token_name": quote_token.get("name"),
                "quote_token_symbol": quote_token.get("symbol"),
                
                # Prix
                "price_native": item.get("priceNative"),
                "price_usd": item.get("priceUsd"),
                
                # Transactions m5
                "txns_m5_buys": txns.get("m5", {}).get("buys"),
                "txns_m5_sells": txns.get("m5", {}).get("sells"),
                
                # Transactions h1
                "txns_h1_buys": txns.get("h1", {}).get("buys"),
                "txns_h1_sells": txns.get("h1", {}).get("sells"),
                
                # Transactions h6
                "txns_h6_buys": txns.get("h6", {}).get("buys"),
                "txns_h6_sells": txns.get("h6", {}).get("sells"),
                
                # Transactions h24
                "txns_h24_buys": txns.get("h24", {}).get("buys"),
                "txns_h24_sells": txns.get("h24", {}).get("sells"),
                
                # Volume
                "volume_m5": volume.get("m5"),
                "volume_h1": volume.get("h1"),
                "volume_h6": volume.get("h6"),
                "volume_h24": volume.get("h24"),
                
                # Changement de prix
                "price_change_m5": price_change.get("m5"),
                "price_change_h1": price_change.get("h1"),
                "price_change_h6": price_change.get("h6"),
                "price_change_h24": price_change.get("h24"),
                
                # Liquidité
                "liquidity_usd": liquidity.get("usd"),
                "liquidity_base": liquidity.get("base"),
                "liquidity_quote": liquidity.get("quote"),
                
                # Métriques
                "fdv": item.get("fdv"),
                "market_cap": item.get("marketCap"),
                "pair_created_at": item.get("pairCreatedAt"),
                
                # Info supplémentaires
                "image_url": info.get("imageUrl"),
                "info_header": info.get("header"),
                "info_open_graph": info.get("openGraph"),
                "info_websites": json.dumps(info.get("websites", [])),
                "info_socials": json.dumps(info.get("socials", [])),
                
                # Boosts
                "boosts_active": boosts.get("active"),
            })
        
        return data

    def _token_exists(self, cursor, token_address: str) -> bool:
        """Vérifie si un token existe déjà dans la base de données"""
        cursor.execute("SELECT 1 FROM tokens WHERE token_address = ?", (token_address,))
        return cursor.fetchone() is not None

    def _insert_token(self, cursor, data: Dict, endpoint_name: str):
        """Insert un nouveau token dans la base de données"""
        data["created_by_endpoint"] = endpoint_name
        data["updated_by_endpoint"] = endpoint_name
        
        columns = ', '.join(data.keys())
        placeholders = ', '.join(['?' for _ in data.keys()])
        
        cursor.execute(f'''
            INSERT INTO tokens ({columns})
            VALUES ({placeholders})
        ''', list(data.values()))

    def _update_token(self, cursor, data: Dict, endpoint_name: str, token_address: str):
        """Met à jour un token existant"""
        # Supprimer les champs qui ne doivent pas être mis à jour
        update_data = data.copy()
        update_data.pop("token_address", None)
        update_data["updated_by_endpoint"] = endpoint_name
        update_data["updated_at"] = datetime.now().isoformat()
        
        # Construire la requête de mise à jour
        set_clause = ', '.join([f"{key} = ?" for key in update_data.keys()])
        values = list(update_data.values()) + [token_address]
        
        cursor.execute(f'''
            UPDATE tokens 
            SET {set_clause}
            WHERE token_address = ?
        ''', values)

    def _log_stats(self, cursor, endpoint_name: str, processed: int, created: int, updated: int):
        """Enregistre les statistiques dans la table stats_log"""
        cursor.execute('''
            INSERT INTO stats_log (endpoint_name, items_processed, items_created, items_updated, cycle_number)
            VALUES (?, ?, ?, ?, ?)
        ''', (endpoint_name, processed, created, updated, self.cumulative_stats["cycles_completed"] + 1))

    def _process_endpoint_data(self, data: List[Dict], endpoint_name: str) -> Tuple[int, int, List[str]]:
        """Traite les données d'un endpoint et retourne (créés, mis à jour, liste des tokens créés)"""
        created_count = 0
        updated_count = 0
        filtered_count = 0
        created_tokens = []
        
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            for item in data:
                # Filtrer uniquement les tokens Solana
                chain_id = item.get("chainId")
                if chain_id != "solana":
                    filtered_count += 1
                    self.logger.debug(f"Token ignoré (chain: {chain_id}): {item.get('url', 'N/A')}")
                    continue
                
                token_address = self._extract_token_address(item, endpoint_name)
                
                if not token_address:
                    self.logger.debug(f"Adresse de token manquante pour l'item: {item}")
                    continue
                
                token_data = self._prepare_token_data(item, endpoint_name)
                
                if self._token_exists(cursor, token_address):
                    self._update_token(cursor, token_data, endpoint_name, token_address)
                    updated_count += 1
                    self.logger.debug(f"Token mis à jour: {token_address}")
                else:
                    self._insert_token(cursor, token_data, endpoint_name)
                    created_count += 1
                    created_tokens.append(token_address)
                    self.logger.debug(f"Nouveau token créé: {token_address}")
            
            # Calculer le nombre d'éléments traités (sans les filtrés)
            processed_count = len(data) - filtered_count
            
            # Enregistrer les statistiques
            self._log_stats(cursor, endpoint_name, processed_count, created_count, updated_count)
            
            conn.commit()
        
        if filtered_count > 0:
            self.logger.debug(f"{endpoint_name}: {filtered_count} tokens non-Solana ignorés")
        
        return created_count, updated_count, created_tokens

    def fetch_and_process_data(self):
        """Récupère et traite les données de tous les endpoints"""
        cycle_created = 0
        cycle_updated = 0
        all_created_tokens = {}  # Dict pour organiser par endpoint
        
        self.logger.info("=== Début du cycle de collecte des données ===")
        
        for endpoint_name, url in self.endpoints.items():
            self.logger.info(f"Traitement de l'endpoint: {endpoint_name}")
            
            # Récupération des données
            raw_data = self._make_request(endpoint_name, url)
            if not raw_data:
                self.logger.warning(f"Aucune donnée récupérée pour {endpoint_name}")
                continue
            
            # Extraction des données selon le type d'endpoint
            if endpoint_name == "search_pumpfun":
                # L'endpoint search retourne un objet avec une clé "pairs"
                data = raw_data.get("pairs", [])
            else:
                # Les autres endpoints retournent directement une liste
                data = raw_data if isinstance(raw_data, list) else []
            
            if not data:
                self.logger.warning(f"Aucun élément trouvé pour {endpoint_name}")
                continue
            
            # Traitement des données
            created, updated, created_tokens = self._process_endpoint_data(data, endpoint_name)
            cycle_created += created
            cycle_updated += updated
            all_created_tokens[endpoint_name] = created_tokens
            
            # Compter les éléments Solana
            solana_count = sum(1 for item in data if item.get("chainId") == "solana")
            
            self.logger.info(f"{endpoint_name}: {created} créés, {updated} mis à jour "
                           f"({solana_count}/{len(data)} tokens Solana traités)")
            
            # Afficher les adresses des nouveaux tokens créés
            if created_tokens:
                self.logger.info(f"[NOUVEAU] Tokens créés pour {endpoint_name}:")
                for token_addr in created_tokens:
                    self.logger.info(f"   -> {token_addr}")
            else:
                self.logger.info(f"[INFO] Aucun nouveau token créé pour {endpoint_name}")
        
        # Mise à jour des statistiques cumulées
        self.cumulative_stats["total_created"] += cycle_created
        self.cumulative_stats["total_updated"] += cycle_updated
        self.cumulative_stats["cycles_completed"] += 1
        
        # Calcul du temps écoulé
        elapsed_time = datetime.now() - self.cumulative_stats["start_time"]
        hours = int(elapsed_time.total_seconds() // 3600)
        minutes = int((elapsed_time.total_seconds() % 3600) // 60)
        
        self.logger.info(f"=== Fin du cycle {self.cumulative_stats['cycles_completed']} ===")
        self.logger.info(f"Cycle actuel: {cycle_created} créés, {cycle_updated} mis à jour (Solana uniquement)")
        
        # Résumé des tokens créés dans ce cycle
        if cycle_created > 0:
            self.logger.info(f"[RESUME CREATIONS] Cycle {self.cumulative_stats['cycles_completed']}:")
            for endpoint, tokens in all_created_tokens.items():
                if tokens:
                    self.logger.info(f"   {endpoint}: {len(tokens)} token(s)")
                    for token in tokens:
                        self.logger.info(f"     * {token}")
        else:
            self.logger.info("[INFO] Aucun nouveau token créé dans ce cycle")
        
        self.logger.info(f"CUMULÉ: {self.cumulative_stats['total_created']} créés, {self.cumulative_stats['total_updated']} mis à jour")
        self.logger.info(f"Temps de fonctionnement: {hours}h{minutes:02d}m")
        
        return cycle_created, cycle_updated

    def get_stats(self) -> Dict:
        """Retourne les statistiques de la base de données"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # Nombre total de tokens
            cursor.execute("SELECT COUNT(*) FROM tokens")
            total_tokens = cursor.fetchone()[0]
            
            # Répartition par endpoint de création
            cursor.execute("""
                SELECT created_by_endpoint, COUNT(*) 
                FROM tokens 
                GROUP BY created_by_endpoint
            """)
            by_endpoint = dict(cursor.fetchall())
            
            # Tokens récemment mis à jour (dernières 24h)
            cursor.execute("""
                SELECT COUNT(*) FROM tokens 
                WHERE updated_at > datetime('now', '-1 day')
            """)
            recent_updates = cursor.fetchone()[0]
            
            # Statistiques par endpoint depuis le début
            cursor.execute("""
                SELECT 
                    endpoint_name,
                    SUM(items_created) as total_created,
                    SUM(items_updated) as total_updated,
                    SUM(items_processed) as total_processed,
                    COUNT(*) as cycles_count
                FROM stats_log 
                GROUP BY endpoint_name
            """)
            endpoint_stats = {}
            for row in cursor.fetchall():
                endpoint_stats[row[0]] = {
                    "created": row[1],
                    "updated": row[2], 
                    "processed": row[3],
                    "cycles": row[4]
                }
            
            return {
                "total_tokens": total_tokens,
                "by_endpoint": by_endpoint,
                "recent_updates": recent_updates,
                "endpoint_stats": endpoint_stats,
                "cumulative": self.cumulative_stats.copy()
            }

    def get_detailed_stats(self) -> Dict:
        """Retourne des statistiques détaillées"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # Top 10 des tokens par volume 24h
            cursor.execute("""
                SELECT base_token_symbol, base_token_name, volume_h24, price_usd, market_cap
                FROM tokens 
                WHERE volume_h24 IS NOT NULL AND volume_h24 > 0
                ORDER BY volume_h24 DESC 
                LIMIT 10
            """)
            top_volume = cursor.fetchall()
            
            # Top 10 des tokens par market cap
            cursor.execute("""
                SELECT base_token_symbol, base_token_name, market_cap, price_usd, volume_h24
                FROM tokens 
                WHERE market_cap IS NOT NULL AND market_cap > 0
                ORDER BY market_cap DESC 
                LIMIT 10
            """)
            top_market_cap = cursor.fetchall()
            
            # Répartition par DEX
            cursor.execute("""
                SELECT dex_id, COUNT(*) as count
                FROM tokens 
                WHERE dex_id IS NOT NULL
                GROUP BY dex_id
                ORDER BY count DESC
            """)
            by_dex = cursor.fetchall()
            
            return {
                "top_volume_24h": top_volume,
                "top_market_cap": top_market_cap,
                "by_dex": by_dex
            }

    def run_forever(self, interval: int = 60):
        """Lance le tracker en continu"""
        self.logger.info(f"Démarrage du tracker DexScreener (intervalle: {interval}s)")
        self.logger.info(f"Heure de début: {self.cumulative_stats['start_time'].strftime('%Y-%m-%d %H:%M:%S')}")
        
        try:
            while True:
                start_time = time.time()
                
                try:
                    self.fetch_and_process_data()
                    
                    # Affichage des statistiques périodiques toutes les 10 cycles
                    if self.cumulative_stats["cycles_completed"] % 10 == 0:
                        stats = self.get_stats()
                        self.logger.info(f"[STATS] Statistiques base: {stats['total_tokens']} tokens total, "
                                       f"{stats['recent_updates']} mis à jour récemment")
                    
                except Exception as e:
                    self.logger.error(f"Erreur durant le cycle: {e}")
                
                # Calcul du temps d'attente
                elapsed = time.time() - start_time
                sleep_time = max(0, interval - elapsed)
                
                if sleep_time > 0:
                    self.logger.debug(f"Attente de {sleep_time:.1f}s avant le prochain cycle")
                    time.sleep(sleep_time)
                else:
                    self.logger.warning(f"Le cycle a pris {elapsed:.1f}s, plus long que l'intervalle de {interval}s")
                    
        except KeyboardInterrupt:
            self.logger.info("Arrêt du tracker demandé par l'utilisateur")
            elapsed_time = datetime.now() - self.cumulative_stats["start_time"]
            self.logger.info(f"Résumé final: {self.cumulative_stats['cycles_completed']} cycles, "
                           f"{self.cumulative_stats['total_created']} créés, "
                           f"{self.cumulative_stats['total_updated']} mis à jour, "
                           f"durée: {elapsed_time}")
        except Exception as e:
            self.logger.critical(f"Erreur critique: {e}")
            raise


def main():
    parser = argparse.ArgumentParser(description='DexScreener Token Tracker')
    parser.add_argument('--db', default='dexscreener.db', help='Chemin vers la base de données SQLite')
    parser.add_argument('--interval', type=int, default=60, help='Intervalle en secondes entre les cycles')
    parser.add_argument('--debug', action='store_true', help='Active le mode debug')
    parser.add_argument('--stats', action='store_true', help='Affiche les statistiques et quitte')
    parser.add_argument('--detailed-stats', action='store_true', help='Affiche les statistiques détaillées')
    parser.add_argument('--once', action='store_true', help='Exécute un seul cycle et quitte')
    
    args = parser.parse_args()
    
    tracker = DexScreenerTracker(db_path=args.db, debug=args.debug)
    
    if args.detailed_stats:
        detailed = tracker.get_detailed_stats()
        print(f"\n=== Statistiques détaillées ===")
        print(f"\n🔥 Top 10 volume 24h:")
        for i, (symbol, name, vol, price, mcap) in enumerate(detailed['top_volume_24h'], 1):
            print(f"  {i:2d}. {symbol} - Vol: ${vol:,.2f} - Prix: ${float(price or 0):.8f}")
        
        print(f"\n💎 Top 10 market cap:")
        for i, (symbol, name, mcap, price, vol) in enumerate(detailed['top_market_cap'], 1):
            print(f"  {i:2d}. {symbol} - MCap: ${mcap:,.0f} - Prix: ${float(price or 0):.8f}")
            
        print(f"\n🏪 Répartition par DEX:")
        for dex, count in detailed['by_dex']:
            print(f"  - {dex}: {count}")
        return
    
    if args.stats:
        stats = tracker.get_stats()
        print(f"\n=== Statistiques de la base de données ===")
        print(f"Tokens total: {stats['total_tokens']}")
        print(f"Mises à jour récentes: {stats['recent_updates']}")
        print(f"Répartition par endpoint:")
        for endpoint, count in stats['by_endpoint'].items():
            print(f"  - {endpoint}: {count}")
        
        print(f"\n=== Statistiques cumulées ===")
        cum = stats['cumulative']
        print(f"Cycles complétés: {cum['cycles_completed']}")
        print(f"Total créés: {cum['total_created']}")
        print(f"Total mis à jour: {cum['total_updated']}")
        if cum['cycles_completed'] > 0:
            elapsed = datetime.now() - cum['start_time']
            print(f"Temps de fonctionnement: {elapsed}")
        
        if stats['endpoint_stats']:
            print(f"\n=== Détail par endpoint ===")
            for endpoint, ep_stats in stats['endpoint_stats'].items():
                print(f"{endpoint}:")
                print(f"  Créés: {ep_stats['created']}, Mis à jour: {ep_stats['updated']}")
                print(f"  Éléments traités: {ep_stats['processed']}, Cycles: {ep_stats['cycles']}")
        return
    
    if args.once:
        tracker.fetch_and_process_data()
        stats = tracker.get_stats()
        print(f"Cycle terminé. Total: {stats['total_tokens']} tokens en base")
        return
    
    tracker.run_forever(args.interval)


if __name__ == "__main__":
    main()