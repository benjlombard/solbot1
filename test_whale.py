

# Script de test rapide (test_whale.py)
import sqlite3
from datetime import datetime

conn = sqlite3.connect('tokens.db')
cursor = conn.cursor()

# Insérer quelques transactions test
test_transactions = [
    ("test_sig_1", "6njWoXd6AeMx3w5ZELFfJjrumnVryymR9a9VSDzapump", "wallet123", "buy", 15000, 1000000, datetime.now(), 0.5, False, "Test Whale", True, "jupiter"),
    ("test_sig_2", "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v", "wallet456", "sell", 75000, 500000, datetime.now(), 1.2, True, "Recurring Whale", True, "raydium")
]

for tx in test_transactions:
    cursor.execute('''
        INSERT OR REPLACE INTO whale_transactions_live 
        (signature, token_address, wallet_address, transaction_type, amount_usd, amount_tokens, timestamp, price_impact, is_known_whale, wallet_label, is_in_database, dex_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', tx)

conn.commit()
conn.close()
print("✅ Test whale transactions inserted")