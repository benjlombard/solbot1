#!/usr/bin/env python3
import asyncio
import aiohttp
import json

async def test_token_progress():
    address = "41vZZpGqBQ2dGxS99cmWZuQuC7X97VbcqiAobp29pump"
    
    async with aiohttp.ClientSession() as session:
        url = f"https://frontend-api.pump.fun/coins/{address}"
        async with session.get(url, timeout=8) as resp:
            if resp.status == 200:
                data = await resp.json()
                print("🔍 Raw Pump.fun data:")
                print(json.dumps(data, indent=2))
                
                # Calculer selon différentes méthodes
                market_cap = data.get("market_cap", 0)
                real_sol = data.get("real_sol_reserves", 0)
                
                print(f"\n📊 Calculs:")
                print(f"Market Cap method (69k target): {(market_cap/69000)*100:.1f}%")
                print(f"Market Cap method (50k target): {(market_cap/50000)*100:.1f}%")
                print(f"SOL reserves method (30 SOL): {(real_sol/30)*100:.1f}%")
                print(f"Direct progress field: {data.get('progress', 'N/A')}")

if __name__ == "__main__":
    asyncio.run(test_token_progress())