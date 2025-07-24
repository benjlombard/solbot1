#!/usr/bin/env python3
"""
🎯 Jupiter Token Scanner – Invest-Ready + Early-Opportunity Edition
✅ Modules optionnels :
   --early          scan ultra-précoce (pump.fun, Raydium new pools)
   --social         veille Twitter (simulé / placeholder API)
   --holders-growth détection de croissance holders
Usage :
   python invest_scanner.py --limit 15 --early --social --holders-growth
"""

import asyncio
import aiohttp
import sqlite3
import time
import json
import argparse
import random
import logging
import csv
import requests
from datetime import datetime
from typing import List, Dict

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("invest_scanner.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)

class InvestScanner:
    TOKEN_LIST_URL = "https://token.jup.ag/all"
    QUOTE_API_URL = "https://quote-api.jup.ag/v6/quote"
    DEXSCREENER_API = "https://api.dexscreener.com/latest"
    IGNORED_TOKENS = {'SOL', 'USDC', 'USDT', 'BTC', 'ETH', 'BONK', 'WIF', 'JUP', 'ORCA', 'RAY'}

    def __init__(self, database_path: str = "invest.db", telegram_token: str = None, telegram_chat_id: str = None,
                 enable_early: bool = False, enable_social: bool = False, enable_holders: bool = False):
        self.database_path = database_path
        self.telegram_token = telegram_token
        self.telegram_chat_id = telegram_chat_id
        # ----- modules optionnels -----
        self.enable_early   = enable_early
        self.enable_social  = enable_social
        self.enable_holders = enable_holders
        # ------------------------------
        self.setup_database()
        self.migrate_database()

    # ---------- BASE DE DONNÉES ----------
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
            rug_score REAL,
            holders INTEGER,
            is_tradeable BOOLEAN DEFAULT 0,
            invest_score REAL,
            early_bonus INTEGER,
            social_bonus INTEGER,
            holders_bonus INTEGER,
            first_discovered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        ''')
        conn.commit()
        conn.close()

    def migrate_database(self):
        conn = sqlite3.connect(self.database_path)
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(tokens)")
        cols = {col[1] for col in cursor.fetchall()}
        for col in ["rug_score", "holders", "invest_score", "early_bonus", "social_bonus", "holders_bonus"]:
            if col not in cols:
                cursor.execute(f"ALTER TABLE tokens ADD COLUMN {col} REAL DEFAULT 0")
        conn.commit()
        conn.close()

    # ---------- OUTILS HTTP ----------
    async def fetch_json(self, url: str, session: aiohttp.ClientSession, timeout: int = 10):
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
                return await resp.json() if resp.status == 200 else None
        except Exception as e:
            logging.debug(f"Error fetching {url}: {e}")
            return None

    # ---------- SOURCES DE DONNÉES ----------
    async def get_jupiter_tokens(self) -> List[Dict]:
        async with aiohttp.ClientSession() as session:
            data = await self.fetch_json(self.TOKEN_LIST_URL, session)
            return data or []

    async def get_dexscreener_data(self, address: str) -> Dict:
        url = f"{self.DEXSCREENER_API}/dex/tokens/{address}"
        async with aiohttp.ClientSession() as session:
            data = await self.fetch_json(url, session)
            if data and data.get("pairs"):
                pair = data["pairs"][0]
                return {
                    "price_usd": float(pair.get("priceUsd", 0)),
                    "market_cap": float(pair.get("marketCap", 0)),
                    "liquidity_usd": float(pair.get("liquidity", {}).get("usd", 0)),
                    "volume_24h": float(pair.get("volume", {}).get("h24", 0)),
                    "price_change_24h": float(pair.get("priceChange", {}).get("h24", 0)),
                    "age_hours": (time.time() * 1000 - pair.get("pairCreatedAt", time.time() * 1000)) / 3600000,
                    "has_dexscreener_data": True
                }
        return {"has_dexscreener_data": False}

    async def check_jupiter_price(self, address: str) -> Dict:
        url = f"{self.QUOTE_API_URL}?inputMint={address}&outputMint=EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v&amount=1000000&slippageBps=500"
        async with aiohttp.ClientSession() as session:
            data = await self.fetch_json(url, session)
            return {"price_usdc": int(data["outAmount"]) / 1e6, "has_price": True} if data else {"price_usdc": 0, "has_price": False}

    async def get_rugcheck_score(self, address: str) -> Dict:
        url = f"https://api.rugcheck.xyz/v1/tokens/{address}/report"
        async with aiohttp.ClientSession() as session:
            data = await self.fetch_json(url, session)
            return {"rug_score": data.get("score", 0)} if data else {"rug_score": 0}

    async def get_holders(self, address: str) -> int:
        url = f"https://public-api.solscan.io/token/holders?tokenAddress={address}&limit=1"
        async with aiohttp.ClientSession() as session:
            data = await self.fetch_json(url, session)
            return data.get("total", 0) if data else 0

    # ---------- MODULES OPTIONNELS ----------
    def early_bonus(self, address: str) -> int:
        """Heuristique simple : mint pump.fun = +10 points"""
        return 10 if self.enable_early and address.startswith("pump") else 0

    def social_bonus(self) -> int:
        """Placeholder API Twitter : 0-20 points aléatoires"""
        return random.randint(0, 20) if self.enable_social else 0

    def holders_bonus(self) -> int:
        """Placeholder croissance holders : 0-20 points aléatoires"""
        return random.randint(0, 20) if self.enable_holders else 0

    # ---------- CALCUL DU SCORE ----------
    def calculate_invest_score(self, data: Dict) -> float:
        risk      = 100 - data.get("rug_score", 50)
        momentum  = min(data.get("volume_24h", 0) / 50_000, 1) * 100
        liquidity = min(data.get("liquidity_usd", 0) / 100_000, 1) * 100
        holders   = min(data.get("holders", 0) / 1_000, 1) * 100
        early     = data.get("early_bonus", 0)
        social    = data.get("social_bonus", 0)
        hbonus    = data.get("holders_bonus", 0)
        score = (
            risk * 0.35 +
            momentum * 0.25 +
            liquidity * 0.15 +
            holders * 0.15 +
            early + social + hbonus
        )
        return round(score, 2)

    # ---------- BASE DE DONNÉES ----------
    def save_token_to_db(self, token: Dict):
        conn = sqlite3.connect(self.database_path)
        cursor = conn.cursor()
        cursor.execute('''
        INSERT OR REPLACE INTO tokens (
            address, symbol, name, decimals, logo_uri, price_usdc, market_cap,
            liquidity_usd, volume_24h, price_change_24h, age_hours,
            rug_score, holders, is_tradeable, invest_score,
            early_bonus, social_bonus, holders_bonus
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            token["address"], token["symbol"], token["name"], token["decimals"],
            token.get("logo_uri"), token.get("price_usdc"), token.get("market_cap"),
            token.get("liquidity_usd"), token.get("volume_24h"), token.get("price_change_24h"),
            token.get("age_hours"), token.get("rug_score"), token.get("holders"),
            token.get("is_tradeable"), token.get("invest_score"),
            token.get("early_bonus"), token.get("social_bonus"), token.get("holders_bonus")
        ))
        conn.commit()
        conn.close()

    def send_telegram(self, message: str):
        if not self.telegram_token or not self.telegram_chat_id:
            return
        url = f"https://api.telegram.org/bot{self.telegram_token}/sendMessage"
        try:
            requests.post(url, json={"chat_id": self.telegram_chat_id, "text": message})
        except Exception as e:
            logging.error(f"Telegram error: {e}")

    def export_csv(self):
        conn = sqlite3.connect(self.database_path)
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM tokens ORDER BY invest_score DESC LIMIT 100")
        rows = cursor.fetchall()
        with open("tokens_export.csv", "w", newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([desc[0] for desc in cursor.description])
            writer.writerows(rows)
        conn.close()
        logging.info("📁 Exported to tokens_export.csv")

    # ---------- SCAN ----------
    async def enrich_token(self, token: Dict) -> Dict:
        address = token["address"]
        logging.info(f"🔍 Enriching {token['symbol']} ({address})")

        dex   = await self.get_dexscreener_data(address)
        jup   = await self.check_jupiter_price(address)
        rug   = await self.get_rugcheck_score(address)
        hold  = await self.get_holders(address)

        enriched = {**token, **dex, **jup, **rug, "holders": hold}
        enriched["is_tradeable"] = jup["has_price"] or dex["has_dexscreener_data"]

        # --- modules optionnels ---
        enriched["early_bonus"]   = self.early_bonus(address)
        enriched["social_bonus"]  = self.social_bonus()
        enriched["holders_bonus"] = self.holders_bonus()

        enriched["invest_score"] = self.calculate_invest_score(enriched)
        return enriched

    async def scan_and_process(self, limit: int = 10):
        all_tokens = await self.get_jupiter_tokens()
        total = len(all_tokens)
        blacklist = {t["symbol"].upper() for t in all_tokens if t["symbol"].upper() in self.IGNORED_TOKENS}
        no_route = [t for t in all_tokens if t["address"] not in blacklist and not (await self.check_jupiter_price(t["address"]))["has_price"]]

        logging.info(f"📦 Source: Jupiter API – Total tokens: {total}")
        logging.info(f"🚫 Ignored classics: {len(blacklist)}")
        logging.info(f"🚫 No Jupiter route: {len(no_route)}")
        candidates = [t for t in all_tokens if t["symbol"].upper() not in self.IGNORED_TOKENS]
        random.shuffle(candidates)
        candidates = candidates[:limit * 2]

        conn = sqlite3.connect(self.database_path)
        cursor = conn.cursor()
        cursor.execute("SELECT address FROM tokens")
        seen = {row[0] for row in cursor.fetchall()}
        conn.close()

        new_tokens = 0
        for token in candidates[:limit]:
            if token["address"] in seen:
                continue
            enriched = await self.enrich_token(token)
            if not enriched["is_tradeable"]:
                logging.info(f"🚫 Skipping {enriched['symbol']} – not tradeable")
                continue

            self.save_token_to_db(enriched)
            logging.info(
                f"📊 {enriched['symbol']} – Score: {enriched['invest_score']} | "
                f"Risk:{100-enriched.get('rug_score',0):.0f} Mom:{min(enriched.get('volume_24h',0)/50_000,1)*100:.0f} "
                f"Liq:{min(enriched.get('liquidity_usd',0)/100_000,1)*100:.0f} Hold:{min(enriched.get('holders',0)/1_000,1)*100:.0f} "
                f"Early:{enriched['early_bonus']} Soc:{enriched['social_bonus']} Hold+:{enriched['holders_bonus']}"
            )
            if enriched["invest_score"] >= 80:
                msg = (
                    f"🚨 EARLY GEM\n"
                    f"Token: {enriched['symbol']}\n"
                    f"Score: {enriched['invest_score']}\n"
                    f"Dex: https://dexscreener.com/solana/{enriched['address']}"
                )
                self.send_telegram(msg)
            new_tokens += 1
            await asyncio.sleep(1)
        return {"new_tokens_found": new_tokens}

    def get_database_stats(self):
        conn = sqlite3.connect(self.database_path)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM tokens")
        total = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM tokens WHERE invest_score >= 80")
        high = cursor.fetchone()[0]
        conn.close()
        return {"total_tokens": total, "high_score_tokens": high}

# ---------- MAIN ----------
def main():
    parser = argparse.ArgumentParser(description="Invest-Ready Solana Token Scanner")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--interval", type=int, default=10)
    parser.add_argument("--database", default="invest.db")
    parser.add_argument("--single-scan", action="store_true")
    parser.add_argument("--stats", action="store_true")
    parser.add_argument("--telegram", action="store_true")
    parser.add_argument("--telegram-token", default=None)
    parser.add_argument("--telegram-chat-id", default=None)

    # modules optionnels
    parser.add_argument("--early", action="store_true", help="enable pump.fun/early detection")
    parser.add_argument("--social", action="store_true", help="enable Twitter mentions")
    parser.add_argument("--holders-growth", action="store_true", help="enable holders growth bonus")

    args = parser.parse_args()

    scanner = InvestScanner(
        database_path=args.database,
        telegram_token=args.telegram_token or (args.telegram and "YOUR_BOT_TOKEN"),
        telegram_chat_id=args.telegram_chat_id or (args.telegram and "YOUR_CHAT_ID"),
        enable_early=args.early,
        enable_social=args.social,
        enable_holders=args.holders_growth
    )

    if args.stats:
        print(scanner.get_database_stats())
        return

    if args.single_scan:
        asyncio.run(scanner.scan_and_process(args.limit))
        scanner.export_csv()
    else:
        async def loop():
            while True:
                print(f"\n🔄 Scanning at {datetime.now().strftime('%H:%M:%S')}")
                result = await scanner.scan_and_process(args.limit)   # ← await, pas asyncio.run
                print(f"⏳ Next scan in {args.interval} minutes")
                await asyncio.sleep(args.interval * 60)
        try:
            asyncio.run(loop())
        except KeyboardInterrupt:
            print("\n✅ Scanner stopped.")

if __name__ == "__main__":
    main()