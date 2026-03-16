#!/usr/bin/env python3
"""Real-time Taiwan/US Stock Price Fetcher for AI Trader.

Fetches current stock prices from Yahoo Finance.
Used by investment-report-evening skill to verify stock prices and prevent
AI hallucination of stock data.

Usage:
    python3 fetch_realtime_prices.py [symbol1] [symbol2] ...

Example:
    python3 fetch_realtime_prices.py 2603.TW 2615.TW 2330.TW
"""
import sys
import json
from datetime import datetime, timezone, timedelta

try:
    import yfinance as yf
except ImportError:
    print("Error: yfinance not installed. Run: pip install yfinance")
    sys.exit(1)

_TZ_TWN = timezone(timedelta(hours=8))

# Taiwan stock suffix mapping
_TWSE_SUFFIX = ".TW"


def fetch_price(symbol: str) -> dict:
    """Fetch real-time price for a single stock symbol."""
    try:
        # Add .TW suffix for Taiwan stocks if not present
        if not symbol.endswith(_TWSE_SUFFIX) and symbol.isdigit():
            symbol = symbol + _TWSE_SUFFIX
        
        ticker = yf.Ticker(symbol)
        
        # Fetch latest info
        info = ticker.info
        price = info.get('currentPrice') or info.get('regularMarketPrice')
        previous_close = info.get('previousClose') or info.get('regularMarketPreviousClose')
        
        if price is None:
            return {"symbol": symbol, "error": "No price data available"}
        
        # Get change info
        change = info.get('regularMarketChange')
        percent_change = info.get('regularMarketChangePercent')
        
        return {
            "symbol": symbol,
            "name": info.get('shortName') or info.get('longName') or symbol,
            "price": round(price, 2),
            "previous_close": round(previous_close, 2) if previous_close else None,
            "change": round(change, 2) if change else None,
            "percent_change": round(percent_change, 2) if percent_change else None,
            "timestamp": datetime.now(_TZ_TWN).isoformat(),
            "source": "Yahoo Finance"
        }
    except Exception as e:
        return {"symbol": symbol, "error": str(e)}


def fetch_batch(symbols: list) -> dict:
    """Fetch prices for multiple symbols."""
    results = {}
    for sym in symbols:
        # Clean symbol
        clean_sym = sym.strip()
        results[clean_sym] = fetch_price(clean_sym)
    
    return {
        "status": "ok",
        "generated_at": datetime.now(_TZ_TWN).isoformat(),
        "prices": results
    }


def main():
    if len(sys.argv) < 2:
        # Default symbols for testing (Taiwan stocks)
        symbols = ["2603.TW", "2615.TW", "2330.TW", "2454.TW", "2317.TW"]
    else:
        symbols = sys.argv[1:]
    
    result = fetch_batch(symbols)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
