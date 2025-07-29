#!/usr/bin/env python3
"""
🧪 Script de test pour la détection whale
Simule des transactions whale réalistes et teste l'API
"""

import sqlite3
import asyncio
import random
from datetime import datetime, timedelta
from whale_detector_integration import whale_detector, WhaleTransaction

# Adresses de tokens réels Solana pour le test
TEST_TOKENS = [
    "So11111111111111111111111111111111111111112",  # SOL
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",  # USDC
    "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",  # USDT
    "mSoLzYCxHdYgdzU16g5QSh3i5K3z3KZK7ytfqcJm7So",   # mSOL
]

# Adresses de wallets whale réels (anonymisées)
TEST_WHALE_WALLETS = [
    "9WzDXwBbmkg8ZTbNMqUxvQRAyrZzDsGYdLVL9zYtAWWM",
    "5Q544fKrFoe6tsEbD7S8EmxGTJYAKtTVhAW5Q5pge4j1", 
    "GThUX1Atko4tqhN2NaiTazWSeFWMuiUidhzHPtjd3rte",
]

async def create_realistic_whale_data():
    """Créer des données whale réalistes dans la base"""
    
    conn = sqlite3.connect("tokens.db")
    cursor = conn.cursor()
    
    # Nettoyer les anciennes données de test
    cursor.execute("DELETE FROM whale_transactions_live WHERE wallet_label LIKE '%TEST%'")
    
    test_transactions = []
    
    # Générer des transactions sur les 24 dernières heures
    for i in range(50):
        # Timestamp aléatoire dans les 24 dernières heures
        hours_ago = random.uniform(0, 24)
        timestamp = datetime.now() - timedelta(hours=hours_ago)
        
        # Paramètres aléatoires mais réalistes
        token_address = random.choice(TEST_TOKENS)
        wallet_address = random.choice(TEST_WHALE_WALLETS)
        transaction_type = random.choice(['buy', 'sell'])
        
        # Montants réalistes selon la distribution whale
        if random.random() < 0.1:  # 10% de mega whales
            amount_usd = random.uniform(100000, 500000)
        elif random.random() < 0.3:  # 30% de whales critiques  
            amount_usd = random.uniform(50000, 100000)
        else:  # 60% de whales normales
            amount_usd = random.uniform(5000, 50000)
        
        signature = f"test_signature_{i}_{int(timestamp.timestamp())}"
        
        test_transactions.append((
            signature,
            token_address,
            wallet_address,
            transaction_type,
            amount_usd,
            amount_usd / random.uniform(0.1, 10),  # amount_tokens approximatif
            timestamp,
            random.uniform(0, 5),  # price_impact
            random.choice([True, False]),  # is_known_whale
            f"TEST Whale #{random.randint(1, 10)}",  # wallet_label
            True,  # is_in_database
            random.choice(['jupiter', 'raydium', 'pump_fun'])  # dex_id
        ))
    
    # Insérer en batch
    cursor.executemany('''
        INSERT INTO whale_transactions_live (
            signature, token_address, wallet_address, transaction_type,
            amount_usd, amount_tokens, timestamp, price_impact,
            is_known_whale, wallet_label, is_in_database, dex_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', test_transactions)
    
    conn.commit()
    conn.close()
    
    print(f"✅ Créé {len(test_transactions)} transactions whale de test")
    print("📊 Distribution des montants:")
    
    # Analyser la distribution
    mega_whales = [tx for tx in test_transactions if tx[4] >= 100000]
    critical_whales = [tx for tx in test_transactions if 50000 <= tx[4] < 100000]
    normal_whales = [tx for tx in test_transactions if 5000 <= tx[4] < 50000]
    
    print(f"   🐋 Mega whales (≥$100K): {len(mega_whales)}")
    print(f"   🔥 Critical whales ($50-100K): {len(critical_whales)}")
    print(f"   💰 Normal whales ($5-50K): {len(normal_whales)}")

async def test_whale_api_endpoints():
    """Tester tous les endpoints de l'API whale"""
    from whale_detector_integration import whale_api
    
    print("\n🧪 Test des endpoints API whale...")
    
    # Test 1: Résumé whale
    summary = whale_api.get_whale_activity_summary()
    print(f"📊 Résumé whale: {summary}")
    
    # Test 2: Activité récente 1h
    recent_1h = whale_api.get_recent_whale_activity(hours=1, limit=10)
    print(f"🕐 Activité 1h: {len(recent_1h)} transactions")
    
    # Test 3: Activité récente 24h
    recent_24h = whale_api.get_recent_whale_activity(hours=24, limit=20)
    print(f"📅 Activité 24h: {len(recent_24h)} transactions")
    
    # Test 4: Activité par token
    if recent_24h:
        test_token = recent_24h[0]['token_address']
        token_activity = whale_api.get_whale_activity_for_token(test_token, hours=24)
        print(f"🎯 Activité pour {test_token}: {len(token_activity)} transactions")
    
    return {
        'summary': summary,
        'recent_1h': len(recent_1h),
        'recent_24h': len(recent_24h),
        'api_working': True
    }

async def test_real_transaction_parsing():
    """Tester le parsing sur de vraies transactions Solana"""
    
    print("\n🔍 Test du parsing de vraies transactions...")
    
    # Signatures de vraies transactions avec gros volumes (exemples)
    real_signatures = [
        # Ces signatures sont des exemples - remplacez par de vraies signatures récentes
        "3KyAjVZXFgJxCfgH8ysP8jFjvkbS5JzKrjJ4QxZbYdvEgKfGpEyGHjXqWzM7ZJFkL2NjHgCxR9jGxYzM5",
        "5MxBjKVzXgFjXcFhEysJ8hGjvBbS7jZKJrJcQxYbZdVtGKpGtJyHjXqFzM9ZGFkR2MjHkCxP9sGzYtF2",
    ]
    
    print("⚠️ Note: Pour tester le parsing réel, vous devez:")
    print("1. Copier des signatures récentes depuis Solscan.io")
    print("2. Chercher des transactions avec 'Jupiter' ou 'Raydium'") 
    print("3. Remplacer les signatures d'exemple ci-dessus")
    
    # Si vous voulez tester avec de vraies signatures:
    """
    for signature in real_signatures:
        try:
            from solana.rpc.async_api import AsyncClient
            client = AsyncClient("https://rpc.helius.xyz/?api-key=872ddf73-4cfd-4263-a418-521bbde27eb8")
            
            # Simuler les logs WebSocket
            logs = [
                f"Program {JUPITER_PROGRAM} invoke [1]",
                "Program log: Instruction: Route",
                "Program data: base64data..."
            ]
            
            whale_tx = await whale_detector.parse_transaction_for_whale_activity(signature, logs)
            if whale_tx:
                print(f"✅ Détecté whale: ${whale_tx.amount_usd:,.0f} {whale_tx.transaction_type}")
            else:
                print(f"❌ Pas de whale détectée pour {signature}")
                
            await client.close()
            
        except Exception as e:
            print(f"❌ Erreur parsing {signature}: {e}")
    """

async def test_dashboard_integration():
    """Tester l'intégration avec le dashboard"""
    
    print("\n🖥️ Test intégration dashboard...")
    
    # Simuler les appels HTTP que fait le dashboard
    import aiohttp
    
    endpoints_to_test = [
        "http://localhost:5000/api/whale-summary",
        "http://localhost:5000/api/whale-feed?hours=1&limit=10", 
        "http://localhost:5000/api/whale-activity?hours=24&limit=100"
    ]
    
    async with aiohttp.ClientSession() as session:
        for url in endpoints_to_test:
            try:
                async with session.get(url) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        print(f"✅ {url}: {len(data.get('whale_transactions', data.get('feed_items', [])))} items")
                    else:
                        print(f"❌ {url}: HTTP {resp.status}")
            except Exception as e:
                print(f"❌ {url}: Connection error - {e}")

async def test_websocket_simulation():
    """Simuler la réception de logs WebSocket"""
    
    print("\n📡 Test simulation WebSocket...")
    
    # Simuler des logs WebSocket typiques
    simulated_logs = [
        {
            "signature": "test_ws_signature_1",
            "logs": [
                "Program JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4 invoke [1]",
                "Program log: Instruction: ExactOutRoute", 
                "Program TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA invoke [2]",
                "Program data: AQAAAAEAAAABAAAAAQAAAAEAAAABAAAAgJaYAAAAAAD//////////w==",
            ]
        },
        {
            "signature": "test_ws_signature_2", 
            "logs": [
                "Program 675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8 invoke [1]",
                "Program log: swap_base_in",
                "Program TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA invoke [2]",
            ]
        }
    ]
    
    # Importer la fonction de traitement
    from whale_detector_integration import process_websocket_logs_for_whales
    
    for log_data in simulated_logs:
        print(f"🔍 Processing signature: {log_data['signature']}")
        try:
            await process_websocket_logs_for_whales(
                log_data['signature'], 
                log_data['logs']
            )
            print(f"✅ Processed {log_data['signature']} successfully")
        except Exception as e:
            print(f"❌ Error processing {log_data['signature']}: {e}")

async def run_complete_whale_test():
    """Lancer tous les tests whale"""
    
    print("🐋 === TEST COMPLET SYSTÈME WHALE === 🐋\n")
    
    # 1. Créer des données de test
    await create_realistic_whale_data()
    
    # 2. Tester les APIs
    api_results = await test_whale_api_endpoints()
    
    # 3. Tester le parsing de transactions
    await test_real_transaction_parsing()
    
    # 4. Tester l'intégration dashboard (si serveur lancé)
    await test_dashboard_integration()
    
    # 5. Tester la simulation WebSocket
    await test_websocket_simulation()
    
    print(f"\n🎉 Tests terminés! API working: {api_results['api_working']}")
    print("📋 Prochaines étapes pour tester en production:")
    print("   1. Lancer solana_monitor_c4.py")
    print("   2. Lancer le dashboard Flask")
    print("   3. Surveiller les logs pour 'Whale activity detected'")
    print("   4. Vérifier l'onglet 'Whale Activity' du dashboard")

if __name__ == "__main__":
    asyncio.run(run_complete_whale_test())