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
from urllib.request import Request, urlopen

import websockets


SYMBOLS = ["RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK", "SBIN"]
YAHOO_SYMBOLS = {
    "RELIANCE": "RELIANCE.NS",
    "TCS": "TCS.NS",
    "INFY": "INFY.NS",
    "HDFCBANK": "HDFCBANK.NS",
    "ICICIBANK": "ICICIBANK.NS",
    "SBIN": "SBIN.NS",
}
TWELVE_SYMBOLS = {
    "RELIANCE": "RELIANCE:NSE",
    "TCS": "TCS:NSE",
    "INFY": "INFY:NSE",
    "HDFCBANK": "HDFCBANK:NSE",
    "ICICIBANK": "ICICIBANK:NSE",
    "SBIN": "SBIN:NSE",
}
PRICE_FILE = Path("prices.json")
API_KEY = os.getenv("FINNHUB_API_KEY", "").strip()
GNEWS_API_KEY = os.getenv("GNEWS_API_KEY", "").strip()
TWELVE_DATA_API_KEY = os.getenv("TWELVE_DATA_API_KEY", "").strip()
live_price_cache = {"expires_at": 0, "payload": None}
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


def json_response(handler, payload, status=200):
    body = json.dumps(payload).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def practice_prices_payload():
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    return {
        "mode": "practice",
        "status": "simulated",
        "source": "StockDesk Simulator",
        "lastUpdated": now,
        "message": "Practice Mode uses simulated prices for learning and paper trading.",
        "prices": prices,
        "meta": {
            symbol: {
                "providerSymbol": symbol,
                "currency": "INR",
                "isSimulated": True,
            }
            for symbol in SYMBOLS
        },
    }


def as_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def fetch_twelve_data_prices():
    live_prices = {}
    meta = {}
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    for symbol, provider_symbol in TWELVE_SYMBOLS.items():
        url = (
            "https://api.twelvedata.com/quote"
            f"?symbol={quote(provider_symbol)}&apikey={quote(TWELVE_DATA_API_KEY)}"
        )
        request = Request(
            url,
            headers={
                "User-Agent": "StockDesk/1.0",
                "Accept": "application/json",
            },
        )

        try:
            with urlopen(request, timeout=10) as response:
                quote_payload = json.loads(response.read().decode("utf-8"))
        except (URLError, TimeoutError, json.JSONDecodeError) as exc:
            meta[symbol] = {
                "providerSymbol": provider_symbol,
                "isSimulated": False,
                "error": str(exc),
            }
            continue

        if quote_payload.get("status") == "error":
            meta[symbol] = {
                "providerSymbol": provider_symbol,
                "isSimulated": False,
                "error": quote_payload.get("message", "Twelve Data returned an error."),
            }
            continue

        price = as_float(quote_payload.get("close")) or as_float(quote_payload.get("price"))
        if price is None:
            meta[symbol] = {
                "providerSymbol": provider_symbol,
                "isSimulated": False,
                "error": "Twelve Data response did not include a usable price.",
            }
            continue

        live_prices[symbol] = round(price, 2)
        prices[symbol] = live_prices[symbol]
        meta[symbol] = {
            "providerSymbol": provider_symbol,
            "currency": quote_payload.get("currency", "INR"),
            "change": as_float(quote_payload.get("change")),
            "changePercent": as_float(quote_payload.get("percent_change")),
            "marketState": "OPEN" if quote_payload.get("is_market_open") else "CLOSED",
            "exchange": quote_payload.get("exchange", "NSE"),
            "delayMinutes": "EOD/delayed",
            "marketTime": quote_payload.get("timestamp"),
            "datetime": quote_payload.get("datetime"),
            "isSimulated": False,
        }

    if not live_prices:
        return None

    save_prices()
    return {
        "mode": "live",
        "status": "live",
        "source": "Twelve Data NSE quotes",
        "lastUpdated": now,
        "message": "Live View uses Twelve Data where your plan supports NSE symbols. NSE data may be delayed or end-of-day depending on plan.",
        "prices": live_prices,
        "meta": meta,
    }


def fetch_yahoo_prices():
    now = time.time()
    if live_price_cache["payload"] and live_price_cache["expires_at"] > now:
        return live_price_cache["payload"]

    yahoo_symbols = ",".join(YAHOO_SYMBOLS.values())
    url = f"https://query1.finance.yahoo.com/v7/finance/quote?symbols={quote(yahoo_symbols, safe=',')}"
    request = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 StockDesk/1.0",
            "Accept": "application/json",
        },
    )

    try:
        with urlopen(request, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (URLError, TimeoutError, json.JSONDecodeError) as exc:
        fallback = practice_prices_payload()
        fallback["mode"] = "live"
        fallback["status"] = "fallback"
        fallback["source"] = "Cached simulator prices"
        fallback["message"] = f"Live prices unavailable. Showing latest local prices. Reason: {exc}"
        return fallback

    reverse_symbols = {value: key for key, value in YAHOO_SYMBOLS.items()}
    live_prices = {}
    meta = {}
    latest_market_time = 0

    for quote_item in payload.get("quoteResponse", {}).get("result", []):
        provider_symbol = quote_item.get("symbol")
        symbol = reverse_symbols.get(provider_symbol)
        price = quote_item.get("regularMarketPrice")
        if not symbol or price is None:
            continue

        live_prices[symbol] = round(float(price), 2)
        prices[symbol] = live_prices[symbol]
        latest_market_time = max(latest_market_time, int(quote_item.get("regularMarketTime") or 0))
        meta[symbol] = {
            "providerSymbol": provider_symbol,
            "currency": quote_item.get("currency", "INR"),
            "change": quote_item.get("regularMarketChange"),
            "changePercent": quote_item.get("regularMarketChangePercent"),
            "marketState": quote_item.get("marketState"),
            "exchange": quote_item.get("fullExchangeName") or quote_item.get("exchange"),
            "delayMinutes": quote_item.get("exchangeDataDelayedBy"),
            "marketTime": quote_item.get("regularMarketTime"),
            "isSimulated": False,
        }

    if not live_prices:
        fallback = practice_prices_payload()
        fallback["mode"] = "live"
        fallback["status"] = "fallback"
        fallback["source"] = "Cached simulator prices"
        fallback["message"] = "Live provider returned no quote data. Showing latest local prices."
        return fallback

    save_prices()
    updated_at = (
        time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(latest_market_time))
        if latest_market_time
        else time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    )
    result = {
        "mode": "live",
        "status": "live",
        "source": "Yahoo Finance delayed quotes",
        "lastUpdated": updated_at,
        "message": "Live View uses delayed NSE quote data when available. Trading remains disabled.",
        "prices": live_prices,
        "meta": meta,
    }
    live_price_cache["payload"] = result
    live_price_cache["expires_at"] = now + 60
    return result


def fetch_live_prices():
    now = time.time()
    if live_price_cache["payload"] and live_price_cache["expires_at"] > now:
        return live_price_cache["payload"]

    if TWELVE_DATA_API_KEY:
        twelve_payload = fetch_twelve_data_prices()
        if twelve_payload:
            live_price_cache["payload"] = twelve_payload
            live_price_cache["expires_at"] = now + 120
            return twelve_payload

    return fetch_yahoo_prices()


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
        if parsed.path == "/api/prices":
            query = parse_qs(parsed.query)
            mode = query.get("mode", ["practice"])[0].lower()
            payload = fetch_live_prices() if mode == "live" else practice_prices_payload()
            json_response(self, payload)
            return

        if parsed.path == "/api/news":
            query = parse_qs(parsed.query)
            symbol = query.get("symbol", ["all"])[0].upper()
            payload = fetch_gnews(symbol)
            json_response(self, payload)
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
