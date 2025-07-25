# File: toto/tata/test_websocket_subscription.py
import asyncio
import json
import logging
import websockets
from decouple import config

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.FileHandler("test_websocket_subscription.log", encoding="utf-8", mode="a", delay=False)]
)
logger = logging.getLogger(__name__)

async def test_subscription():
    HELIUS_WS_URL = f"wss://rpc.helius.xyz/?api-key={config('HELIUS_API_KEY', default='')}"
    PUMP_FUN_PROGRAM = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"
    try:
        async with websockets.connect(HELIUS_WS_URL, ping_interval=20, ping_timeout=10) as ws:
            logger.info("Connected to Helius WebSocket")
            subscription = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "logsSubscribe",
                "params": [
                    {"mentions": [PUMP_FUN_PROGRAM]},
                    {"commitment": "finalized"}
                ]
            }
            await ws.send(json.dumps(subscription))
            logger.debug("Sent subscription request")
            for _ in range(10):  # Capture 10 messages
                message = await ws.recv()
                logger.debug(f"Received: {message[:200]}...")
                await asyncio.sleep(1)
    except websockets.exceptions.WebSocketException as e:
        logger.error(f"WebSocket error: {str(e)}")
    finally:
        if logger.handlers:
            logger.handlers[0].flush()

asyncio.run(test_subscription())