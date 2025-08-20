# helius_setup.py
import requests
import json
from config import Config

def create_helius_webhook():
    """Crée les webhooks Helius nécessaires"""
    
    webhook_config = {
        "webhookURL": "https://your-domain.com/helius/webhook",
        "transactionTypes": ["Any"],
        "accountAddresses": [],
        "webhookType": "enhanced",
        "authHeader": "Bearer your-auth-token"
    }
    
    # Webhook pour transactions Raydium
    response = requests.post(
        f"https://api.helius.xyz/v0/webhooks?api-key={Config.HELIUS_API_KEY}",
        json=webhook_config
    )
    
    if response.status_code == 200:
        print("✅ Webhook Helius créé avec succès")
        return response.json()
    else:
        print(f"❌ Erreur création webhook: {response.text}")
        return None

def test_webhook_connection():
    """Teste la connexion avec Helius"""
    test_url = f"https://api.helius.xyz/v0/webhooks?api-key={Config.HELIUS_API_KEY}"
    
    response = requests.get(test_url)
    if response.status_code == 200:
        print("✅ Connexion Helius OK")
        webhooks = response.json()
        print(f"📊 Webhooks actifs: {len(webhooks)}")
        return True
    else:
        print("❌ Problème connexion Helius")
        return False

if __name__ == "__main__":
    test_webhook_connection()
    create_helius_webhook()