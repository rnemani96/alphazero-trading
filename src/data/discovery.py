"""
AlphaZero Capital - Dynamic Stock Discovery
src/data/discovery.py

Fetches NIFTY index constituents directly from NSE to avoid hardcoding.
Filters by recent performance (momentum) to find trade candidates.
"""

import logging
import io
import os
import json
import time
import pandas as pd
import yfinance as yf
import requests
from typing import List, Dict

logger = logging.getLogger("Discovery")


from src.data.universe import get_nifty500_symbols

def _clean_symbol(s: str) -> str:
    if not s: return ""
    return str(s).split(":")[0].split(".")[0].strip()

def fetch_nse_symbols(index: str = "NIFTY 500") -> List[str]:
    """
    Downloads the latest constituent list using centralized data module.
    """
    return get_nifty500_symbols(use_cache=True)


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
    symbols = [_clean_symbol(s) for s in symbols if s and _clean_symbol(s).upper() not in ["UNDEFINED", "NONE", "NULL", "NAN", "N/A"]]
    
    # Chunk the download to avoid yfinance timeouts/limitations
    CHUNK_SIZE = 50 # Smaller chunks are more reliable for bulk data
    from src.data.multi_source_data import get_msd
    msd = get_msd()
    
    logger.info(f"Downloading data for {len(symbols)} stocks via MultiSourceData (chunks of {CHUNK_SIZE})...")
    
    try:
        all_results = {}
        for i in range(0, len(symbols), CHUNK_SIZE):
            chunk = symbols[i : i + CHUNK_SIZE]
            logger.debug(f"Processing chunk {i//CHUNK_SIZE + 1} ({len(chunk)} symbols)...")
            batch_results = msd.get_bulk_candles(chunk, period="5d", interval="1d")
            if batch_results:
                all_results.update(batch_results)
            # Small delay to avoid aggressive rate limiting
            time.sleep(0.5)
        
        if not all_results:
            logger.warning("No data returned from MSD bulk candles. Falling back to default list.")
            return [{"symbol": s, "sector": "AUTO"} for s in symbols[:limit]]
            
        for sym in symbols:
            try:
                series = [b.close for b in all_results.get(sym, [])]
                if len(series) < 2:
                    continue
                
                # Performance = (Today / Yesterday - 1)
                pct = (series[-1] / series[-2] - 1) * 100
                
                perf_data.append({
                    "symbol": sym,
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
        
    symbols = [_clean_symbol(s) for s in symbols if s]
    from src.data.multi_source_data import get_msd
    msd = get_msd()
    
    movers = []
    try:
        batch_results = msd.get_bulk_candles(symbols, period="2d", interval="1d")
        
        if not batch_results:
            return {"gainers": [], "losers": []}
            
        for sym in symbols:
            try:
                series = [b.close for b in batch_results.get(sym, [])]
                if len(series) < 2:
                    continue
                
                pct = (series[-1] / series[-2] - 1) * 100
                movers.append({
                    "symbol": sym,
                    "change": pct,
                    "price": series[-1]
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
