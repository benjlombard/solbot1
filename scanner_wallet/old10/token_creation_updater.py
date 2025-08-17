import sqlite3
import requests
import time
import json
from datetime import datetime
from typing import Optional, Dict, Any

class TokenCreationUpdater:
    def __init__(self, db_path: str, quicknode_url: str = None, dexscreener_delay: float = 0.5):
        """
        Initialise l'updater avec les paramètres de connexion
        
        Args:
            db_path: Chemin vers la base SQLite
            quicknode_url: URL de votre endpoint QuickNode (optionnel)
            dexscreener_delay: Délai entre les appels à DexScreener (secondes)
        """
        self.db_path = db_path
        self.quicknode_url = quicknode_url
        self.dexscreener_delay = dexscreener_delay
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        
    def connect_db(self):
        """Connexion à la base de données"""
        return sqlite3.connect(self.db_path)
    
    def add_timestamp_column(self):
        """Ajoute la colonne timestamp_token_created si elle n'existe pas"""
        with self.connect_db() as conn:
            try:
                conn.execute("""
                    ALTER TABLE transactions 
                    ADD COLUMN timestamp_token_created INTEGER
                """)
                print("✅ Colonne timestamp_token_created ajoutée")
            except sqlite3.OperationalError as e:
                if "duplicate column name" in str(e).lower():
                    print("ℹ️ Colonne timestamp_token_created existe déjà")
                else:
                    raise e
    
    def get_unique_tokens(self) -> list:
        """Récupère la liste des tokens uniques dans la table"""
        with self.connect_db() as conn:
            cursor = conn.execute("""
                SELECT DISTINCT token_mint 
                FROM transactions 
                WHERE token_mint IS NOT NULL 
                AND token_mint != ''
                AND timestamp_token_created IS NULL
                ORDER BY token_mint
            """)
            return [row[0] for row in cursor.fetchall()]
    
    def get_token_creation_from_dexscreener(self, token_address: str) -> Optional[int]:
        """
        Récupère le timestamp de création depuis DexScreener
        
        Args:
            token_address: Adresse du token
            
        Returns:
            Timestamp Unix de création ou None si non trouvé
        """
        try:
            # API DexScreener pour récupérer les infos du token
            url = f"https://api.dexscreener.com/latest/dex/tokens/{token_address}"
            
            response = self.session.get(url, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            
            if 'pairs' in data and data['pairs']:
                # Prendre le pair le plus ancien (première création)
                oldest_pair = min(data['pairs'], key=lambda p: p.get('pairCreatedAt', float('inf')))
                
                if 'pairCreatedAt' in oldest_pair:
                    # pairCreatedAt est généralement en millisecondes
                    creation_time = oldest_pair['pairCreatedAt']
                    if creation_time > 1e12:  # Si en millisecondes
                        creation_time = creation_time // 1000
                    return int(creation_time)
            
            print(f"⚠️ Pas de données de création trouvées pour {token_address[:8]}...")
            return None
            
        except requests.RequestException as e:
            print(f"❌ Erreur API DexScreener pour {token_address[:8]}...: {e}")
            return None
        except Exception as e:
            print(f"❌ Erreur inattendue pour {token_address[:8]}...: {e}")
            return None
    
    def get_token_creation_from_solanatracker(self, token_address: str) -> Optional[int]:
        """
        Récupère le timestamp de création depuis Solana Tracker
        
        Args:
            token_address: Adresse du token
            
        Returns:
            Timestamp Unix de création ou None si non trouvé
        """
        try:
            # API Solana Tracker (nécessite une clé API pour des appels fréquents)
            url = f"https://api.solanatracker.io/tokens/{token_address}"
            
            response = self.session.get(url, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            
            if 'token' in data and 'creation' in data['token']:
                creation_info = data['token']['creation']
                if 'created_time' in creation_info:
                    return int(creation_info['created_time'])
            
            print(f"⚠️ Pas de données de création trouvées sur SolanaTracker pour {token_address[:8]}...")
            return None
            
        except requests.RequestException as e:
            print(f"❌ Erreur API SolanaTracker pour {token_address[:8]}...: {e}")
            return None
        except Exception as e:
            print(f"❌ Erreur inattendue SolanaTracker pour {token_address[:8]}...: {e}")
            return None
    
    def get_token_creation_from_quicknode(self, token_address: str) -> Optional[int]:
        """
        Récupère le timestamp de création via QuickNode (méthode alternative)
        
        Cette méthode nécessiterait d'interroger l'historique des transactions
        pour trouver la première transaction de création du token.
        
        Args:
            token_address: Adresse du token
            
        Returns:
            Timestamp Unix de création ou None si non trouvé
        """
        if not self.quicknode_url:
            return None
            
        try:
            # Cette approche nécessiterait une implémentation plus complexe
            # pour parcourir l'historique des transactions du token
            # et trouver la transaction de création initiale
            
            # Pour l'instant, on retourne None
            # Une implémentation complète nécessiterait:
            # 1. getSignaturesForAddress pour récupérer toutes les signatures
            # 2. getTransaction pour chaque signature
            # 3. Analyser les instructions pour trouver la création du token
            
            print(f"ℹ️ Récupération via QuickNode non implémentée pour {token_address[:8]}...")
            return None
            
        except Exception as e:
            print(f"❌ Erreur QuickNode pour {token_address[:8]}...: {e}")
            return None
    
    def get_token_creation_timestamp(self, token_address: str) -> Optional[int]:
        """
        Récupère le timestamp de création d'un token en essayant plusieurs sources
        
        Args:
            token_address: Adresse du token
            
        Returns:
            Timestamp Unix de création ou None si non trouvé
        """
        print(f"🔍 Recherche création pour {token_address[:8]}...")
        
        # Essayer DexScreener en premier (plus fiable)
        timestamp = self.get_token_creation_from_dexscreener(token_address)
        if timestamp:
            print(f"✅ Trouvé sur DexScreener: {datetime.fromtimestamp(timestamp)}")
            return timestamp
        
        # Pause pour éviter le rate limiting
        time.sleep(self.dexscreener_delay)
        
        # Essayer Solana Tracker
        timestamp = self.get_token_creation_from_solanatracker(token_address)
        if timestamp:
            print(f"✅ Trouvé sur SolanaTracker: {datetime.fromtimestamp(timestamp)}")
            return timestamp
        
        # Pause supplémentaire
        time.sleep(self.dexscreener_delay)
        
        # Essayer QuickNode (si configuré)
        timestamp = self.get_token_creation_from_quicknode(token_address)
        if timestamp:
            print(f"✅ Trouvé via QuickNode: {datetime.fromtimestamp(timestamp)}")
            return timestamp
        
        print(f"❌ Timestamp de création non trouvé pour {token_address[:8]}...")
        return None
    
    def update_token_timestamp(self, token_address: str, timestamp: int):
        """
        Met à jour le timestamp de création d'un token dans la base de données
        
        Args:
            token_address: Adresse du token
            timestamp: Timestamp Unix de création
        """
        with self.connect_db() as conn:
            conn.execute("""
                UPDATE transactions 
                SET timestamp_token_created = ? 
                WHERE token_mint = ?
            """, (timestamp, token_address))
            print(f"💾 Timestamp mis à jour pour {token_address[:8]}...")
    
    def update_all_tokens(self, max_tokens: int = None, start_from: int = 0):
        """
        Met à jour les timestamps de création pour tous les tokens
        
        Args:
            max_tokens: Nombre maximum de tokens à traiter (None = tous)
            start_from: Index de début (pour reprendre après interruption)
        """
        # Ajouter la colonne si nécessaire
        self.add_timestamp_column()
        
        # Récupérer les tokens à traiter
        tokens = self.get_unique_tokens()
        total_tokens = len(tokens)
        
        print(f"📊 {total_tokens} tokens à traiter")
        
        if start_from > 0:
            tokens = tokens[start_from:]
            print(f"▶️ Début à partir du token #{start_from}")
        
        if max_tokens:
            tokens = tokens[:max_tokens]
            print(f"🔢 Limitation à {max_tokens} tokens")
        
        success_count = 0
        failed_count = 0
        
        for i, token_address in enumerate(tokens, start=start_from + 1):
            print(f"\n[{i}/{total_tokens}] Traitement de {token_address}")
            
            try:
                timestamp = self.get_token_creation_timestamp(token_address)
                
                if timestamp:
                    self.update_token_timestamp(token_address, timestamp)
                    success_count += 1
                else:
                    failed_count += 1
                
                # Pause entre les tokens pour éviter le rate limiting
                time.sleep(self.dexscreener_delay)
                
            except KeyboardInterrupt:
                print(f"\n⏹️ Interruption utilisateur à l'index {i}")
                break
            except Exception as e:
                print(f"❌ Erreur lors du traitement de {token_address}: {e}")
                failed_count += 1
                continue
        
        print(f"\n📈 Résumé:")
        print(f"✅ Succès: {success_count}")
        print(f"❌ Échecs: {failed_count}")
        print(f"📊 Total traité: {success_count + failed_count}")

def main():
    """Fonction principale pour exécuter le script"""
    
    # Configuration
    DB_PATH = "solana_wallet_monitor.db"  # Remplacer par votre chemin
    QUICKNODE_URL = None  # Optionnel: "https://your-endpoint.quiknode.pro/"
    
    # Créer l'updater
    updater = TokenCreationUpdater(
        db_path=DB_PATH,
        quicknode_url=QUICKNODE_URL,
        dexscreener_delay=0.5  # 500ms entre les appels
    )
    
    print("🚀 Démarrage de la mise à jour des timestamps de création de tokens")
    
    try:
        # Traiter tous les tokens (ou limiter avec max_tokens=10 pour tester)
        updater.update_all_tokens(
            max_tokens=None,  # None = tous les tokens
            start_from=0      # 0 = commencer au début
        )
        
    except Exception as e:
        print(f"❌ Erreur fatale: {e}")
    
    print("\n🏁 Traitement terminé")

if __name__ == "__main__":
    main()