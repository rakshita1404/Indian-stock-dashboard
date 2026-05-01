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
live_price_cache = {}
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


def live_fallback_payload(symbol, message):
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    return {
        "mode": "live",
        "status": "fallback",
        "source": "Cached simulator prices",
        "lastUpdated": now,
        "message": message,
        "prices": {symbol: prices.get(symbol, 0)},
        "meta": {
            symbol: {
                "providerSymbol": symbol,
                "currency": "INR",
                "isSimulated": True,
                "error": message,
            }
        },
    }


def fetch_twelve_data_price(symbol):
    provider_symbol = TWELVE_SYMBOLS.get(symbol)
    if not provider_symbol:
        return None

    live_prices = {}
    meta = {}
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

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
        return live_fallback_payload(symbol, f"Twelve Data request failed. Showing fallback price. Reason: {exc}")

    if quote_payload.get("status") == "error":
        return live_fallback_payload(
            symbol,
            quote_payload.get("message", "Twelve Data returned an error. Showing fallback price."),
        )

    price = as_float(quote_payload.get("close")) or as_float(quote_payload.get("price"))
    if price is None:
        return live_fallback_payload(symbol, "Twelve Data response did not include a usable price. Showing fallback price.")

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

    save_prices()
    return {
        "mode": "live",
        "status": "live",
        "source": "Twelve Data NSE quotes",
        "lastUpdated": now,
        "message": f"Fetched only {symbol} from Twelve Data to save API credits. NSE data may be delayed or end-of-day depending on plan.",
        "prices": live_prices,
        "meta": meta,
    }


def fetch_yahoo_price(symbol):
    provider_symbol = YAHOO_SYMBOLS.get(symbol)
    if not provider_symbol:
        return live_fallback_payload(symbol, "No fallback provider symbol configured. Showing fallback price.")

    url = f"https://query1.finance.yahoo.com/v7/finance/quote?symbols={quote(provider_symbol)}"
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
        return live_fallback_payload(symbol, f"Yahoo fallback unavailable. Showing fallback price. Reason: {exc}")

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
        return live_fallback_payload(symbol, "Yahoo fallback returned no quote data. Showing fallback price.")

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
        "message": f"Fetched only {symbol} from Yahoo fallback. Trading remains disabled.",
        "prices": live_prices,
        "meta": meta,
    }
    return result


def fetch_live_prices(symbol):
    symbol = symbol if symbol in SYMBOLS else "INFY"
    cache_key = f"live:{symbol}"
    now = time.time()
    cached = live_price_cache.get(cache_key)
    if cached and cached["expires_at"] > now:
        return cached["payload"]

    if TWELVE_DATA_API_KEY:
        payload = fetch_twelve_data_price(symbol)
        if payload and payload["status"] == "live":
            live_price_cache[cache_key] = {"payload": payload, "expires_at": now + 120}
            return payload
        if payload:
            yahoo_payload = fetch_yahoo_price(symbol)
            if yahoo_payload["status"] == "live":
                yahoo_payload["message"] = f"Twelve Data did not return live data for {symbol}. Using Yahoo fallback to save Twelve credits."
                live_price_cache[cache_key] = {"payload": yahoo_payload, "expires_at": now + 60}
                return yahoo_payload
            live_price_cache[cache_key] = {"payload": payload, "expires_at": now + 60}
            return payload

    payload = fetch_yahoo_price(symbol)
    live_price_cache[cache_key] = {"payload": payload, "expires_at": now + 60}
    return payload


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
            symbol = query.get("symbol", ["INFY"])[0].upper()
            payload = fetch_live_prices(symbol) if mode == "live" else practice_prices_payload()
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
