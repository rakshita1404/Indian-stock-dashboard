import asyncio
import json
import math
import os
import random
import time
from functools import partial
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from threading import Thread

import websockets


SYMBOLS = ["RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK", "SBIN"]
PRICE_FILE = Path("prices.json")
API_KEY = os.getenv("FINNHUB_API_KEY", "").strip()
prices = {
    "RELIANCE": 2935.40,
    "TCS": 3820.25,
    "INFY": 1488.60,
    "HDFCBANK": 1712.35,
    "ICICIBANK": 1128.90,
    "SBIN": 771.45,
}


def save_prices():
    PRICE_FILE.write_text(json.dumps(prices, indent=2), encoding="utf-8")


async def stream_finnhub_prices():
    url = f"wss://ws.finnhub.io?token={API_KEY}"
    async with websockets.connect(url) as ws:
        for symbol in SYMBOLS:
            await ws.send(json.dumps({"type": "subscribe", "symbol": symbol}))

        while True:
            msg = json.loads(await ws.recv())
            if msg.get("type") == "trade":
                for trade in msg["data"]:
                    if trade["s"] in SYMBOLS:
                        prices[trade["s"]] = round(trade["p"], 2)
                save_prices()


async def stream_demo_prices():
    while True:
        now = time.time()
        for index, symbol in enumerate(SYMBOLS):
            base = prices[symbol]
            wave = math.sin(now / 8 + index) * base * 0.0015
            noise = random.uniform(-base * 0.0008, base * 0.0008)
            prices[symbol] = round(max(1, base + wave + noise), 2)
        save_prices()
        await asyncio.sleep(1.5)


async def fetch_prices():
    if not API_KEY:
        print("FINNHUB_API_KEY is not set. Running demo price stream.")
        await stream_demo_prices()
        return

    while True:
        try:
            await stream_finnhub_prices()
        except Exception as exc:
            print(f"Finnhub stream unavailable: {exc}. Retrying in 5 seconds.")
            await asyncio.sleep(5)


def start_http():
    handler = partial(SimpleHTTPRequestHandler, directory=str(Path(__file__).parent))
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    server = ThreadingHTTPServer((host, port), handler)
    print(f"Serving dashboard at http://{host}:{port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    save_prices()
    Thread(target=start_http, daemon=False).start()
    print("Stock dashboard price stream started.", flush=True)
    asyncio.run(fetch_prices())
