#!/usr/bin/env python3
"""
Jupiter Token Database Scanner – Version corrigée & filtrée
✅ Filtre automatique des tokens sans route
✅ Indicateur `is_tradeable` basé sur Jupiter + DexScreener
Usage: python jupiter_db_scanner.py --interval 10 --limit 15 --database tokens.db
"""

import asyncio
import aiohttp
import sqlite3
import time
import json
import argparse
import random
import logging
from datetime import datetime
from typing import List, Dict

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("token_scanner.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)

class TokenDatabaseScanner:
    TOKEN_LIST_URL = "https://token.jup.ag/all"
    QUOTE_API_URL = "https://quote-api.jup.ag/v6/quote"
    DEXSCREENER_API = "https://api.dexscreener.com/latest"
    IGNORED_TOKENS = {'SOL', 'USDC', 'USDT', 'BTC', 'ETH', 'BONK', 'WIF', 'JUP', 'ORCA', 'RAY'}

    def __init__(self, database_path: str = "tokens.db"):
        self.database_path = database_path
        self.setup_database()
        self.migrate_database()

    def setup_database(self):
        conn = sqlite3.connect(self.database_path)
        cursor = conn.cursor()
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS tokens (
            address TEXT PRIMARY KEY,
            symbol TEXT NOT NULL,
            name TEXT,
            decimals INTEGER,
            logo_uri TEXT,
            price_usdc REAL,
            market_cap REAL,
            liquidity_usd REAL,
            volume_24h REAL,
            price_change_24h REAL,
            age_hours REAL,
            quality_score REAL,
            has_dexscreener_data BOOLEAN DEFAULT 0,
            is_tradeable BOOLEAN DEFAULT 0,
            jupiter_ok BOOLEAN DEFAULT 0,
            dex_ok BOOLEAN DEFAULT 0,
            first_discovered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        ''')
        conn.commit()
        conn.close()

    def migrate_database(self):
        conn = sqlite3.connect(self.database_path)
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(tokens)")
        cols = {col[1] for col in cursor.fetchall()}
        for col in ["is_tradeable", "jupiter_ok", "dex_ok"]:
            if col not in cols:
                cursor.execute(f"ALTER TABLE tokens ADD COLUMN {col} BOOLEAN DEFAULT 0")
        conn.commit()
        conn.close()

    async def fetch_json(self, url: str, session: aiohttp.ClientSession, timeout: int = 10):
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
                if resp.status == 200:
                    return await resp.json()
                else:
                    logging.debug(f"HTTP {resp.status} for {url}")
        except Exception as e:
            logging.debug(f"Error fetching {url}: {e}")
        return None

    async def get_jupiter_tokens(self) -> List[Dict]:
        async with aiohttp.ClientSession() as session:
            data = await self.fetch_json(self.TOKEN_LIST_URL, session)
            return data or []

    async def get_dexscreener_data(self, token_address: str) -> Dict:
        url = f"{self.DEXSCREENER_API}/dex/tokens/{token_address}"
        async with aiohttp.ClientSession() as session:
            data = await self.fetch_json(url, session)
            if data and "pairs" in data and data["pairs"]:
                pair = data["pairs"][0]
                return {
                    "has_dexscreener_data": True,
                    "price_usd": float(pair.get("priceUsd", 0)),
                    "market_cap": float(pair.get("marketCap", 0)),
                    "liquidity_usd": float(pair.get("liquidity", {}).get("usd", 0)),
                    "volume_24h": float(pair.get("volume", {}).get("h24", 0)),
                    "price_change_24h": float(pair.get("priceChange", {}).get("h24", 0)),
                    "age_hours": (time.time() * 1000 - pair.get("pairCreatedAt", time.time() * 1000)) / 3600000
                }
        return {"has_dexscreener_data": False}

    async def check_jupiter_price(self, token_address: str) -> Dict:
        url = f"{self.QUOTE_API_URL}?inputMint={token_address}&outputMint=EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v&amount=1000000&slippageBps=500"
        async with aiohttp.ClientSession() as session:
            data = await self.fetch_json(url, session)
            if data and "outAmount" in data:
                return {
                    "has_price": True,
                    "price_usdc": int(data["outAmount"]) / 1e6,
                    "route_count": len(data.get("routePlan", [])),
                    "dexes": [step.get("swapInfo", {}).get("label", "Unknown") for step in data.get("routePlan", [])]
                }
        return {"has_price": False}

    async def check_tradeability(self, token_address: str) -> Dict:
        jupiter_data = await self.check_jupiter_price(token_address)
        dex_data = await self.get_dexscreener_data(token_address)
        jupiter_ok = jupiter_data.get("has_price", False) and jupiter_data.get("price_usdc", 0) > 0
        dex_ok = dex_data.get("has_dexscreener_data", False) and dex_data.get("liquidity_usd", 0) > 100
        return {
            "is_tradeable": jupiter_ok or dex_ok,
            "jupiter_ok": jupiter_ok,
            "dex_ok": dex_ok
        }

    def calculate_quality_score(self, token_data: Dict) -> float:
        liquidity = token_data.get("liquidity_usd", 0)
        volume = token_data.get("volume_24h", 0)
        age = token_data.get("age_hours", 0)
        change = abs(token_data.get("price_change_24h", 0))
        score = min(liquidity / 100000, 1) * 30 + min(volume / 50000, 1) * 30
        score += max(0, 1 - age / 24) * 20 + max(0, 1 - change / 50) * 20
        return round(score, 2)

    def save_token_to_db(self, token_data: Dict):
        conn = sqlite3.connect(self.database_path)
        cursor = conn.cursor()
        cursor.execute('''
        INSERT OR REPLACE INTO tokens (
            address, symbol, name, decimals, logo_uri, price_usdc, market_cap,
            liquidity_usd, volume_24h, price_change_24h, age_hours, quality_score,
            has_dexscreener_data, is_tradeable, jupiter_ok, dex_ok, last_updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ''', (
            token_data["address"], token_data["symbol"], token_data["name"],
            token_data["decimals"], token_data.get("logo_uri"),
            token_data.get("price_usdc"), token_data.get("market_cap"),
            token_data.get("liquidity_usd"), token_data.get("volume_24h"),
            token_data.get("price_change_24h"), token_data.get("age_hours"),
            token_data.get("quality_score", 0),
            token_data.get("has_dexscreener_data", False),
            token_data.get("is_tradeable", False),
            token_data.get("jupiter_ok", False),
            token_data.get("dex_ok", False)
        ))
        conn.commit()
        conn.close()

    def token_exists_in_db(self, address: str) -> bool:
        conn = sqlite3.connect(self.database_path)
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM tokens WHERE address = ?", (address,))
        exists = cursor.fetchone() is not None
        conn.close()
        return exists

    async def enrich_token_data(self, token: Dict) -> Dict:
        address = token["address"]
        symbol = token["symbol"]
        logging.info(f"Enriching {symbol} ({address})")
        dex_data = await self.get_dexscreener_data(address)
        jupiter_data = await self.check_jupiter_price(address)
        tradeability = await self.check_tradeability(address)
        enriched = {**token, **dex_data, **jupiter_data, **tradeability}
        enriched["quality_score"] = self.calculate_quality_score(enriched)
        return enriched

    async def scan_and_process_tokens(self, limit: int = 20) -> Dict:
        all_tokens = await self.get_jupiter_tokens()
        candidates = [t for t in all_tokens if t["symbol"].upper() not in self.IGNORED_TOKENS]
        random.shuffle(candidates)
        candidates = candidates[:limit * 2]
        new_tokens = 0

        for token in candidates[:limit]:
            address = token["address"]
            if self.token_exists_in_db(address):
                logging.info(f"⏭️ Skipping existing: {token['symbol']}")
                continue

            enriched = await self.enrich_token_data(token)

            if not enriched.get("is_tradeable"):
                logging.info(f"🚫 Skipping {enriched['symbol']} - not tradeable (Jupiter: {enriched['jupiter_ok']}, Dex: {enriched['dex_ok']})")
                continue

            self.save_token_to_db(enriched)
            print(f"✅ Saved: {enriched['symbol']} - Score: {enriched['quality_score']} (Jupiter: {enriched['jupiter_ok']}, Dex: {enriched['dex_ok']})")
            new_tokens += 1
            await asyncio.sleep(0.5)

        return {"new_tokens_found": new_tokens}

    def get_database_stats(self):
        conn = sqlite3.connect(self.database_path)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM tokens")
        total = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM tokens WHERE is_tradeable = 1")
        tradeable = cursor.fetchone()[0]
        conn.close()
        return {"total_tokens": total, "tradeable_tokens": tradeable}

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=15)
    parser.add_argument("--interval", type=int, default=10)
    parser.add_argument("--database", default="tokens.db")
    parser.add_argument("--single-scan", action="store_true")
    parser.add_argument("--stats", action="store_true")
    args = parser.parse_args()

    scanner = TokenDatabaseScanner(args.database)

    if args.stats:
        stats = scanner.get_database_stats()
        print("📊 DATABASE STATS")
        for k, v in stats.items():
            print(f"{k}: {v}")
        return

    if args.single_scan:
        asyncio.run(scanner.scan_and_process_tokens(args.limit))
    else:
        async def loop():
            while True:
                print(f"\n🔄 Scanning at {datetime.now().strftime('%H:%M:%S')}")
                result = asyncio.run(scanner.scan_and_process_tokens(args.limit))
                print(f"⏳ Next scan in {args.interval} minutes")
                await asyncio.sleep(args.interval * 60)
        try:
            asyncio.run(loop())
        except KeyboardInterrupt:
            print("\n✅ Scanner stopped.")

if __name__ == "__main__":
    main()