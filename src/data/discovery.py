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
    symbols = [_clean_symbol(s) for s in symbols if s]
    yf_symbols = [f"{s}.NS" for s in symbols]
    
    # Chunk the download to avoid yfinance timeouts/limitations
    CHUNK_SIZE = 100
    all_data = []
    
    logger.info(f"Downloading data for {len(yf_symbols)} stocks via yfinance (chunks of {CHUNK_SIZE})...")
    
    try:
        for i in range(0, len(yf_symbols), CHUNK_SIZE):
            chunk = yf_symbols[i:i + CHUNK_SIZE]
            try:
                chunk_data = yf.download(chunk, period="5d", interval="1d", progress=False, group_by='ticker')
                if not chunk_data.empty:
                    all_data.append(chunk_data)
                # Small throttle between chunks
                time.sleep(1)
            except Exception as chunk_err:
                logger.warning(f"Chunk download failed for {len(chunk)} symbols: {chunk_err}")
                continue

        if not all_data:
            logger.warning("No data returned from any yfinance chunks. Falling back to default list.")
            return [{"symbol": s, "sector": "AUTO"} for s in symbols[:limit]]
            
        # Merge all dataframes
        data = pd.concat(all_data, axis=1)
            
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
        
    symbols = [_clean_symbol(s) for s in symbols if s]
    yf_symbols = [f"{s}.NS" for s in symbols]
    movers = []
    CHUNK_SIZE = 100
    all_chunks = []
    
    logger.info(f"Downloading data for {len(yf_symbols)} stocks via yfinance (chunks of {CHUNK_SIZE})...")
    
    try:
        for i in range(0, len(yf_symbols), CHUNK_SIZE):
            chunk = yf_symbols[i:i + CHUNK_SIZE]
            try:
                chunk_data = yf.download(chunk, period="2d", interval="1d", progress=False, group_by='ticker')
                if not chunk_data.empty:
                    all_chunks.append(chunk_data)
                time.sleep(1)
            except Exception as e:
                logger.warning(f"Movers chunk failed: {e}")
                continue

        if not all_chunks:
            return {"gainers": [], "losers": []}
            
        data = pd.concat(all_chunks, axis=1)
            
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
