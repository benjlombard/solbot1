#!/usr/bin/env python3
"""
Pump.fun Direct API Monitor
Utilise l'API directe découverte dans les DevTools
"""

import requests
import time
import sys
import argparse
import json
from datetime import datetime
from typing import List, Dict, Set

class PumpFunDirectMonitor:
    def __init__(self, token_address: str):
        self.token_address = token_address
        self.seen_replies: Set[str] = set()
        
        # URL de l'API directe découverte
        self.api_url = f"https://frontend-api-v3.pump.fun/replies/{token_address}"
        
        # Paramètres de l'API
        self.params = {
            'limit': 1000,
            'offset': 0,
            'reverseOrder': 'true'
        }
        
        # Headers pour simuler un navigateur réel
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'Referer': 'https://pump.fun/',
            'Origin': 'https://pump.fun',
            'Connection': 'keep-alive',
            'Sec-Fetch-Dest': 'empty',
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Site': 'same-site',
            'sec-ch-ua': '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Windows"'
        }
        
        # Mots-clés à surveiller
        self.keywords = [
            'LOCK', 'LOCKED', 'LOCKING',
            'BURN', 'BURNED', 'BURNING',
            'RENOUNCE', 'RENOUNCED',
            'SUPPLY', 'DEV SUPPLY',
            'YEARS', 'YEAR',
            'PARTNERSHIP', 'PARTNER',
            'LISTING', 'LIST',
            'AUDIT', 'AUDITED',
            'DOXXED', 'DOX',
            'RUG', 'RUGPULL',
            'TEAM', 'DEVELOPER',
            'GRADUATED', 'GRADUATE'
        ]
    
    def get_replies(self) -> List[Dict]:
        """Récupère les replies via l'API directe"""
        try:
            response = requests.get(
                self.api_url,
                params=self.params,
                headers=self.headers,
                timeout=15
            )
            
            if response.status_code == 200:
                try:
                    data = response.json()
                    if isinstance(data, list):
                        return data
                    elif isinstance(data, dict):
                        # La structure est {"replies": [...], "hasMore": bool, "offset": int}
                        if 'replies' in data and isinstance(data['replies'], list):
                            print(f"✅ Structure API détectée: {len(data['replies'])} replies, hasMore: {data.get('hasMore', 'N/A')}")
                            return data['replies']
                        else:
                            print(f"Structure de réponse inattendue: {type(data)}")
                            print(f"Clés disponibles: {list(data.keys())}")
                            return []
                    else:
                        print(f"Type de données inattendu: {type(data)}")
                        return []
                        
                except json.JSONDecodeError as e:
                    print(f"Erreur de décodage JSON: {e}")
                    print(f"Contenu reçu: {response.text[:200]}...")
                    return []
            else:
                print(f"Erreur HTTP {response.status_code}: {response.text[:200]}")
                return []
                
        except requests.exceptions.RequestException as e:
            print(f"Erreur de requête: {e}")
            return []
    
    def check_keywords(self, text: str) -> List[str]:
        """Vérifie si le texte contient des mots-clés importants"""
        if not text:
            return []
            
        text_upper = text.upper()
        found_keywords = []
        
        for keyword in self.keywords:
            if keyword in text_upper:
                found_keywords.append(keyword)
        
        return found_keywords
    
    def send_alert(self, reply: Dict, keywords: List[str]):
        """Envoie une alerte pour un reply important"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        print("=" * 60)
        print(f"🚨 ALERTE TOKEN: {self.token_address}")
        print(f"⏰ Timestamp: {timestamp}")
        print(f"🔍 Mots-clés détectés: {', '.join(keywords)}")
        print(f"👤 Utilisateur: {reply.get('username', reply.get('user', 'Inconnu'))}")
        print(f"💬 Message: {reply.get('text', reply.get('content', reply.get('message', 'N/A')))}")
        
        # Afficher des infos supplémentaires si disponibles
        if 'timestamp' in reply:
            reply_time = datetime.fromtimestamp(reply['timestamp'] / 1000) if reply['timestamp'] > 1e10 else datetime.fromtimestamp(reply['timestamp'])
            print(f"📅 Date du reply: {reply_time.strftime('%Y-%m-%d %H:%M:%S')}")
        
        if 'user_id' in reply:
            print(f"🆔 User ID: {reply['user_id']}")
            
        print("=" * 60)
        print()
        
        # Sauvegarde
        self.log_alert(reply, keywords, timestamp)
    
    def log_alert(self, reply: Dict, keywords: List[str], timestamp: str):
        """Sauvegarde l'alerte dans un fichier log"""
        log_entry = {
            'timestamp': timestamp,
            'token': self.token_address,
            'keywords': keywords,
            'reply_data': reply
        }
        
        filename = f"pumpfun_alerts_{self.token_address[:8]}.json"
        
        try:
            try:
                with open(filename, 'r', encoding='utf-8') as f:
                    alerts = json.load(f)
            except FileNotFoundError:
                alerts = []
            
            alerts.append(log_entry)
            
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(alerts, f, indent=2, ensure_ascii=False)
                
            print(f"💾 Alerte sauvegardée dans {filename}")
            
        except Exception as e:
            print(f"❌ Erreur lors de la sauvegarde: {e}")
    
    def display_replies_debug(self, replies: List[Dict]):
        """Affiche les détails des replies en mode debug"""
        print("\n" + "="*60)
        print("📋 DÉTAIL DES REPLIES TROUVÉES:")
        print("="*60)
        
        for i, reply in enumerate(replies, 1):
            text = reply.get('text', reply.get('content', reply.get('message', 'N/A')))
            user = reply.get('username', reply.get('user', reply.get('author', 'Inconnu')))
            
            # Essayer de parser le timestamp
            timestamp_field = reply.get('timestamp', reply.get('created_at', reply.get('time', 'N/A')))
            if isinstance(timestamp_field, (int, float)) and timestamp_field > 0:
                # Convertir timestamp Unix (gérer millisecondes)
                ts = timestamp_field / 1000 if timestamp_field > 1e10 else timestamp_field
                formatted_time = datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M:%S')
            else:
                formatted_time = str(timestamp_field)
            
            print(f"\n📝 Reply #{i}:")
            print(f"👤 Utilisateur: {user}")
            print(f"⏰ Timestamp: {formatted_time}")
            print(f"💬 Texte: {text}")
            
            # Afficher autres champs intéressants
            for key, value in reply.items():
                if key not in ['text', 'content', 'message', 'username', 'user', 'author', 'timestamp', 'created_at', 'time']:
                    if len(str(value)) < 100:  # Éviter les champs trop longs
                        print(f"📊 {key}: {value}")
            
            # Vérifier les mots-clés
            found_keywords = self.check_keywords(text)
            if found_keywords:
                print(f"🚨 Mots-clés détectés: {', '.join(found_keywords)}")
            else:
                print("⚪ Aucun mot-clé détecté")
                
            print("-" * 40)
        
        print("="*60)
    
    def monitor(self, interval: int = 30, debug: bool = False):
        """Lance la surveillance continue"""
        print(f"🔍 Surveillance du token: {self.token_address}")
        print(f"🌐 API: {self.api_url}")
        print(f"⏱️ Intervalle: {interval} secondes")
        print(f"🔑 Mots-clés: {', '.join(self.keywords)}")
        if debug:
            print("🔧 Mode DEBUG activé")
        print("=" * 60)
        
        while True:
            try:
                print(f"\n[{datetime.now().strftime('%H:%M:%S')}] 🔄 Récupération des replies...")
                
                replies = self.get_replies()
                
                if not replies:
                    print("⚠️ Aucun reply récupéré")
                    if debug:
                        print("🔧 Mode debug - Arrêt après le premier scan")
                        break
                else:
                    print(f"✅ {len(replies)} replies récupérées")
                    
                    if debug:
                        self.display_replies_debug(replies)
                        print("\n🔧 Mode debug - Arrêt après le premier scan")
                        break
                
                new_alerts = 0
                
                for reply in replies:
                    # Créer un ID unique pour éviter les doublons
                    text = reply.get('text', reply.get('content', reply.get('message', '')))
                    user = reply.get('username', reply.get('user', reply.get('author', 'unknown')))
                    reply_id = f"{user}_{text[:50]}"
                    
                    if reply_id in self.seen_replies:
                        continue
                    
                    self.seen_replies.add(reply_id)
                    
                    # Vérifier les mots-clés
                    found_keywords = self.check_keywords(text)
                    
                    if found_keywords:
                        self.send_alert(reply, found_keywords)
                        new_alerts += 1
                
                if new_alerts == 0:
                    print("✅ Scan terminé - Aucune nouvelle alerte")
                else:
                    print(f"🚨 {new_alerts} nouvelle(s) alerte(s) détectée(s)")
                
                time.sleep(interval)
                
            except KeyboardInterrupt:
                print("\n⛔ Surveillance arrêtée par l'utilisateur")
                break
            except Exception as e:
                print(f"❌ Erreur inattendue: {e}")
                print("🔄 Reprise dans 30 secondes...")
                time.sleep(30)

def main():
    parser = argparse.ArgumentParser(description='Surveille les replies d\'un token via l\'API directe Pump.fun')
    parser.add_argument('token', help='Adresse du token à surveiller')
    parser.add_argument('-i', '--interval', type=int, default=30,
                        help='Intervalle entre les vérifications en secondes (défaut: 30)')
    parser.add_argument('-d', '--debug', action='store_true',
                        help='Mode debug - affiche tous les replies et s\'arrête après un scan')
    
    args = parser.parse_args()
    
    if len(args.token) < 32:
        print("❌ Erreur: L'adresse du token semble invalide")
        sys.exit(1)
    
    monitor = PumpFunDirectMonitor(args.token)
    monitor.monitor(args.interval, debug=args.debug)

if __name__ == "__main__":
    main()