"""
AlphaZero Capital - Dynamic Stock Discovery
src/data/discovery.py

Fetches NIFTY index constituents directly from NSE to avoid hardcoding.
Filters by recent performance (momentum) to find trade candidates.
"""

import logging
import io
import pandas as pd
import yfinance as yf
import requests
from typing import List, Dict

logger = logging.getLogger("Discovery")

# NSE Index List URLs
NSE_URLS = {
    "NIFTY 50":  "https://archives.nseindia.com/content/indices/ind_nifty50list.csv",
    "NIFTY 100": "https://archives.nseindia.com/content/indices/ind_nifty100list.csv",
    "NIFTY 500": "https://archives.nseindia.com/content/indices/ind_nifty500list.csv",
}

def fetch_nse_symbols(index: str = "NIFTY 100") -> List[str]:
    """
    Downloads the latest constituent list from NSE.
    """
    url = NSE_URLS.get(index, NSE_URLS["NIFTY 100"])
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code == 200:
            df = pd.read_csv(io.StringIO(response.text))
            # Column is usually 'Symbol'
            for col in ['Symbol', 'SYMBOL', 'symbol']:
                if col in df.columns:
                    return df[col].tolist()
        return []
    except Exception as e:
        logger.warning(f"Failed to fetch {index} constituents from NSE: {e}. Using fallback.")
        # Return a safe fallback list if NSE is blocking us
        return ["RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK", "KOTAKBANK", "LT", "SBIN", "BHARTIARTL", "ITC"]

def get_best_performing_stocks(limit: int = 40) -> List[Dict]:
    # Simple file-based cache to avoid heavy yfinance calls on every restart
    cache_file = "data/cache/discovery_cache.json"
    os.makedirs(os.path.dirname(cache_file), exist_ok=True)
    
    if os.path.exists(cache_file):
        try:
            with open(cache_file, "r") as f:
                cached = json.load(f)
            # Cache duration: 1 hour (3600s)
            if time.time() - cached.get("timestamp", 0) < 3600:
                logger.info("Using cached best performers (fresh)")
                return cached.get("stocks", [])[:limit]
        except Exception:
            pass

    symbols = fetch_nse_symbols("NIFTY 500")
    if not symbols:
        return []
        
    perf_data = []
    # Remove any unwanted symbols or handle formatting
    symbols = [str(s).strip() for s in symbols if s]
    yf_symbols = [f"{s}.NS" for s in symbols]
    
    logger.info(f"Downloading data for {len(yf_symbols)} stocks via yfinance...")
    try:
        # Fetch 5 days to compute change relative to yesterday
        # progress=False to keep logs clean
        data = yf.download(yf_symbols, period="5d", interval="1d", progress=False, group_by='ticker')
        if data.empty:
            return [{"symbol": s, "sector": "AUTO"} for s in symbols[:limit]]
            
        for sym_ns in yf_symbols:
            try:
                # Handle multi-index if necessary (group_by='ticker' helps)
                if sym_ns not in data.columns.get_level_values(0):
                    continue
                
                ticker_data = data[sym_ns]
                if 'Close' not in ticker_data.columns:
                    continue
                    
                series = ticker_data['Close'].dropna()
                if len(series) < 2:
                    continue
                
                # Performance = (Today / Yesterday - 1)
                pct = (series.iloc[-1] / series.iloc[-2] - 1) * 100
                
                perf_data.append({
                    "symbol": sym_ns.replace(".NS", ""),
                    "change": pct,
                    "sector": "AUTO"
                })
            except Exception:
                continue
            
        # Sort by best performers
        perf_data.sort(key=lambda x: x['change'], reverse=True)
        top_stocks = perf_data[:limit]
        
        # Save to cache
        try:
            with open(cache_file, "w") as f:
                json.dump({"timestamp": time.time(), "stocks": perf_data}, f, indent=2)
        except Exception as e:
            logger.debug(f"Failed to write discovery cache: {e}")

        logger.info(f"Top performers found: {[s['symbol'] for s in top_stocks[:5]]}")
        return top_stocks

    except Exception as e:
        logger.error(f"Discovery momentum scan failed: {e}")
        return [{"symbol": s, "sector": "AUTO"} for s in symbols[:limit]]
def get_market_movers(limit: int = 10, index: str = "NIFTY 100") -> Dict[str, List[Dict]]:
    """
    Discovers both top gainers and top losers from the specified index.
    Useful for training agents on diverse market scenarios.
    """
    logger.info(f"Scanning {index} for top/bottom movers...")
    
    symbols = fetch_nse_symbols(index)
    if not symbols:
        return {"gainers": [], "losers": []}
        
    yf_symbols = [f"{s}.NS" for s in symbols]
    movers = []
    
    try:
        data = yf.download(yf_symbols, period="2d", interval="1d", progress=False, group_by='ticker')
        if data.empty:
            return {"gainers": [], "losers": []}
            
        for sym_ns in yf_symbols:
            try:
                if sym_ns not in data.columns.get_level_values(0):
                    continue
                ticker_data = data[sym_ns]
                series = ticker_data['Close'].dropna()
                if len(series) < 2:
                    continue
                
                pct = (series.iloc[-1] / series.iloc[-2] - 1) * 100
                movers.append({
                    "symbol": sym_ns.replace(".NS", ""),
                    "change": pct,
                    "price": series.iloc[-1]
                })
            except Exception:
                continue
            
        # Sort
        sorted_movers = sorted(movers, key=lambda x: x['change'], reverse=True)
        top_gainers = sorted_movers[:limit]
        top_losers = sorted_movers[-limit:][::-1] # Reverse to get worst first
        
        logger.info(f"Movers found: {len(top_gainers)} gainers, {len(top_losers)} losers")
        return {
            "gainers": top_gainers,
            "losers": top_losers
        }

    except Exception as e:
        logger.error(f"Movers scan failed: {e}")
        return {"gainers": [], "losers": []}
