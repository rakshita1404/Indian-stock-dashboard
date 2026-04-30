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
from urllib.error import URLError
from urllib.parse import parse_qs, quote, urlparse
from urllib.request import urlopen

import websockets


SYMBOLS = ["RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK", "SBIN"]
PRICE_FILE = Path("prices.json")
API_KEY = os.getenv("FINNHUB_API_KEY", "").strip()
GNEWS_API_KEY = os.getenv("GNEWS_API_KEY", "").strip()
prices = {
    "RELIANCE": 2935.40,
    "TCS": 3820.25,
    "INFY": 1488.60,
    "HDFCBANK": 1712.35,
    "ICICIBANK": 1128.90,
    "SBIN": 771.45,
}

DEMO_NEWS = [
    {
        "symbol": "RELIANCE",
        "title": "Reliance investors track retail, telecom, and energy margins",
        "description": "Demo feed: Watch refining margins, Jio growth, and retail expansion themes.",
        "source": "StockDesk Demo",
    },
    {
        "symbol": "TCS",
        "title": "IT services sentiment follows deal wins and global tech spending",
        "description": "Demo feed: Large deals, BFSI budgets, and margin commentary remain key signals.",
        "source": "StockDesk Demo",
    },
    {
        "symbol": "HDFCBANK",
        "title": "Private bank focus stays on deposit growth and net interest margins",
        "description": "Demo feed: Deposit mobilization, credit growth, and asset quality shape sentiment.",
        "source": "StockDesk Demo",
    },
    {
        "symbol": "INFY",
        "title": "Infosys outlook linked to guidance and discretionary client demand",
        "description": "Demo feed: Revenue guidance, attrition, and digital demand are useful watch points.",
        "source": "StockDesk Demo",
    },
]


def save_prices():
    PRICE_FILE.write_text(json.dumps(prices, indent=2), encoding="utf-8")


def demo_news_payload(symbol="all"):
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    articles = [
        {
            **item,
            "url": "",
            "publishedAt": now,
            "isDemo": True,
        }
        for item in DEMO_NEWS
        if symbol == "all" or item["symbol"] == symbol
    ]
    return {
        "status": "demo",
        "source": "StockDesk Demo",
        "lastUpdated": now,
        "message": "Set GNEWS_API_KEY on Render to show recent market news from the internet.",
        "articles": articles,
    }


def fetch_gnews(symbol="all"):
    if not GNEWS_API_KEY:
        return demo_news_payload(symbol)

    company_names = {
        "RELIANCE": "Reliance Industries",
        "TCS": "Tata Consultancy Services",
        "INFY": "Infosys",
        "HDFCBANK": "HDFC Bank",
        "ICICIBANK": "ICICI Bank",
        "SBIN": "State Bank of India",
    }
    query = "Indian stock market NSE"
    if symbol in company_names:
        query = f"{company_names[symbol]} stock India"

    url = (
        "https://gnews.io/api/v4/search"
        f"?q={quote(query)}&lang=en&country=in&max=8&apikey={quote(GNEWS_API_KEY)}"
    )

    try:
        with urlopen(url, timeout=8) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (URLError, TimeoutError, json.JSONDecodeError) as exc:
        fallback = demo_news_payload(symbol)
        fallback["status"] = "fallback"
        fallback["message"] = f"Live news unavailable. Showing demo feed. Reason: {exc}"
        return fallback

    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    articles = []
    for article in payload.get("articles", []):
        articles.append(
            {
                "symbol": symbol if symbol != "all" else "MARKET",
                "title": article.get("title", "Market update"),
                "description": article.get("description") or "Open the article for more details.",
                "url": article.get("url", ""),
                "publishedAt": article.get("publishedAt", now),
                "source": (article.get("source") or {}).get("name", "GNews"),
                "isDemo": False,
            }
        )

    return {
        "status": "live",
        "source": "GNews",
        "lastUpdated": now,
        "message": "Recent articles from GNews. Availability depends on provider plan and indexing.",
        "articles": articles,
    }


class DashboardHandler(SimpleHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/news":
            query = parse_qs(parsed.query)
            symbol = query.get("symbol", ["all"])[0].upper()
            payload = fetch_gnews(symbol)
            body = json.dumps(payload).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        super().do_GET()


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
    handler = partial(DashboardHandler, directory=str(Path(__file__).parent))
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
