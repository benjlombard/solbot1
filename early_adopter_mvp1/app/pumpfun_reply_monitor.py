#!/usr/bin/env python3
"""
Pump.fun Token Reply Monitor
Surveille les replies d'un token et alerte sur les mots-clés importants
"""

import requests
import time
import sys
import argparse
from datetime import datetime
import json
from typing import List, Dict, Set

class PumpFunMonitor:
    def __init__(self, token_address: str):
        self.token_address = token_address
        # Essayer différentes versions de l'API
        self.base_urls = [
            "https://frontend-api-v3.pump.fun",
            "https://frontend-api-v2.pump.fun", 
            "https://frontend-api.pump.fun"
        ]
        self.current_base_url = None
        self.seen_replies: Set[str] = set()
        self._test_api_endpoints()
        
        # Mots-clés à surveiller (basés sur votre exemple COPE)
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
            'TEAM', 'DEVELOPER'
        ]
    
    def _test_api_endpoints(self):
        """Test différents endpoints pour trouver celui qui fonctionne"""
        print("🔍 Test des endpoints API...")
        
        for base_url in self.base_urls:
            try:
                url = f"{base_url}/replies/{self.token_address}"
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                    'Accept': 'application/json',
                    'Referer': 'https://pump.fun/',
                    'Origin': 'https://pump.fun',
                }
                
                response = requests.get(url, headers=headers, timeout=5)
                
                if response.status_code == 200:
                    try:
                        data = response.json()
                        self.current_base_url = base_url
                        print(f"✅ API fonctionnelle trouvée: {base_url}")
                        print(f"📊 Nombre de replies récupérées: {len(data) if isinstance(data, list) else 'Structure inconnue'}")
                        return
                    except json.JSONDecodeError:
                        continue
                        
            except requests.exceptions.RequestException:
                continue
        
        print("❌ Aucun endpoint API fonctionnel trouvé")
        print("💡 Suggestions:")
        print("   - Vérifiez que l'adresse du token est correcte")
        print("   - Le token existe peut-être pas encore sur Pump.fun")
        print("   - Essayez avec un autre token connu")
        
    def get_replies(self) -> List[Dict]:
        """Récupère les replies pour le token"""
        if not self.current_base_url:
            print("❌ Aucun endpoint API disponible")
            return []
            
        try:
            url = f"{self.current_base_url}/replies/{self.token_address}"
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Accept': 'application/json',
                'Accept-Language': 'en-US,en;q=0.9',
                'Referer': 'https://pump.fun/',
                'Origin': 'https://pump.fun',
                'Cache-Control': 'no-cache',
                'Pragma': 'no-cache'
            }
            
            response = requests.get(url, headers=headers, timeout=10)
            
            if response.status_code == 404:
                print(f"⚠️ Token non trouvé: {self.token_address}")
                return []
            elif response.status_code == 429:
                print("⚠️ Rate limit atteint, attente de 60 secondes...")
                time.sleep(60)
                return []
            elif response.status_code != 200:
                print(f"⚠️ Code de statut HTTP: {response.status_code}")
                return []
            
            if not response.text.strip():
                print("⚠️ Réponse vide de l'API")
                return []
                
            try:
                data = response.json()
                
                if isinstance(data, list):
                    return data
                elif isinstance(data, dict) and 'replies' in data:
                    return data['replies']
                elif isinstance(data, dict) and 'data' in data:
                    return data['data']
                else:
                    print(f"⚠️ Structure de données inattendue: {type(data)}")
                    print(f"Clés disponibles: {list(data.keys()) if isinstance(data, dict) else 'N/A'}")
                    return []
                    
            except json.JSONDecodeError as e:
                print(f"❌ Erreur JSON: {e}")
                print(f"Contenu reçu: {response.text[:200]}...")
                return []
                
        except requests.exceptions.Timeout:
            print("⚠️ Timeout de la requête")
            return []
        except requests.exceptions.ConnectionError:
            print("⚠️ Erreur de connexion")
            return []
        except requests.exceptions.RequestException as e:
            print(f"❌ Erreur de requête: {e}")
            return []
    
    def check_keywords(self, text: str) -> List[str]:
        """Vérifie si le texte contient des mots-clés importants"""
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
        print(f"👤 Utilisateur: {reply.get('username', 'Anonyme')}")
        print(f"💬 Message: {reply.get('text', 'N/A')}")
        
        # Informations supplémentaires si disponibles
        if 'timestamp' in reply:
            print(f"📅 Date du message: {reply['timestamp']}")
        
        print("=" * 60)
        print()
        
        # Vous pouvez ajouter ici d'autres types d'alertes :
        # - Webhook Discord/Slack
        # - Email
        # - Notification desktop
        # - Sauvegarde dans un fichier log
        
        # Exemple de sauvegarde dans un fichier
        self.log_alert(reply, keywords, timestamp)
    
    def log_alert(self, reply: Dict, keywords: List[str], timestamp: str):
        """Sauvegarde l'alerte dans un fichier log"""
        log_entry = {
            'timestamp': timestamp,
            'token': self.token_address,
            'keywords': keywords,
            'username': reply.get('username', 'Anonyme'),
            'message': reply.get('text', 'N/A'),
            'reply_data': reply
        }
        
        filename = f"pumpfun_alerts_{self.token_address[:8]}.json"
        
        try:
            # Lire les alertes existantes
            try:
                with open(filename, 'r', encoding='utf-8') as f:
                    alerts = json.load(f)
            except FileNotFoundError:
                alerts = []
            
            # Ajouter la nouvelle alerte
            alerts.append(log_entry)
            
            # Sauvegarder
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(alerts, f, indent=2, ensure_ascii=False)
                
            print(f"💾 Alerte sauvegardée dans {filename}")
            
        except Exception as e:
            print(f"❌ Erreur lors de la sauvegarde: {e}")
    
    def monitor(self, interval: int = 30):
        """Lance la surveillance continue"""
        if not self.current_base_url:
            print("❌ Impossible de démarrer la surveillance - aucun endpoint fonctionnel")
            return
            
        print(f"🔍 Démarrage de la surveillance pour le token: {self.token_address}")
        print(f"🌐 API utilisée: {self.current_base_url}")
        print(f"⏱️ Intervalle de vérification: {interval} secondes")
        print(f"🔑 Mots-clés surveillés: {', '.join(self.keywords)}")
        print("=" * 60)
        
        consecutive_errors = 0
        max_consecutive_errors = 5
        
        while True:
            try:
                replies = self.get_replies()
                
                if replies is None:
                    consecutive_errors += 1
                    if consecutive_errors >= max_consecutive_errors:
                        print(f"❌ Trop d'erreurs consécutives ({max_consecutive_errors}), arrêt du monitoring")
                        break
                    continue
                else:
                    consecutive_errors = 0  # Reset counter on success
                
                new_alerts = 0
                
                if len(replies) == 0:
                    timestamp = datetime.now().strftime("%H:%M:%S")
                    print(f"[{timestamp}] ℹ️ Aucun reply trouvé pour ce token")
                
                for reply in replies:
                    # Créer un ID unique pour chaque reply
                    reply_text = reply.get('text', reply.get('content', ''))
                    reply_user = reply.get('username', reply.get('user', reply.get('author', 'anon')))
                    reply_id = f"{reply_user}_{reply_text[:50]}"
                    
                    # Éviter les doublons
                    if reply_id in self.seen_replies:
                        continue
                    
                    self.seen_replies.add(reply_id)
                    
                    # Vérifier les mots-clés
                    found_keywords = self.check_keywords(reply_text)
                    
                    if found_keywords:
                        self.send_alert(reply, found_keywords)
                        new_alerts += 1
                
                if new_alerts == 0:
                    timestamp = datetime.now().strftime("%H:%M:%S")
                    total_replies = len(replies)
                    print(f"[{timestamp}] ✅ Scan terminé - {total_replies} replies scannées, aucune nouvelle alerte")
                else:
                    print(f"🚨 {new_alerts} nouvelle(s) alerte(s) détectée(s)")
                
                # Attendre avant le prochain scan
                time.sleep(interval)
                
            except KeyboardInterrupt:
                print("\n⛔ Surveillance arrêtée par l'utilisateur")
                break
            except Exception as e:
                consecutive_errors += 1
                print(f"❌ Erreur inattendue: {e}")
                if consecutive_errors < max_consecutive_errors:
                    print("🔄 Tentative de reprise dans 30 secondes...")
                    time.sleep(30)
                else:
                    print(f"❌ Trop d'erreurs consécutives, arrêt du monitoring")
                    break

def main():
    parser = argparse.ArgumentParser(description='Surveille les replies d\'un token Pump.fun')
    parser.add_argument('token', help='Adresse du token à surveiller')
    parser.add_argument('-i', '--interval', type=int, default=30, 
                        help='Intervalle entre les vérifications en secondes (défaut: 30)')
    
    args = parser.parse_args()
    
    # Validation basique de l'adresse du token
    if len(args.token) < 32:
        print("❌ Erreur: L'adresse du token semble invalide")
        sys.exit(1)
    
    # Créer et lancer le monitor
    monitor = PumpFunMonitor(args.token)
    monitor.monitor(args.interval)

if __name__ == "__main__":
    main()