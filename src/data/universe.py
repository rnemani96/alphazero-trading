"""
src/data/universe.py  —  AlphaZero Capital
═══════════════════════════════════════════
Centralized Stock Universe Management.
Dynamically fetches NIFTY 500 constituents from NSE and manages sector mapping.
"""

import os, json, logging, requests, io, csv
from pathlib import Path
from typing import List, Dict, Any, Optional

logger = logging.getLogger("Universe")

ROOT = Path(__file__).resolve().parents[2]
CACHE_PATH = ROOT / "data" / "cache" / "nifty500_universe.json"
CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)

NSE_NIFTY500_URL = "https://archives.nseindia.com/content/indices/ind_nifty500list.csv"

def get_nifty500_symbols(use_cache: bool = True) -> List[str]:
    """
    Fetch the latest NIFTY 500 symbols from NSE.
    Returns a list of symbols (e.g., ["RELIANCE", "TCS"]).
    """
    if use_cache and CACHE_PATH.exists():
        try:
            with open(CACHE_PATH, 'r') as f:
                syms = json.load(f)
                if len(syms) > 100:
                    return syms
        except Exception: pass

    logger.info("Fetching NIFTY 500 universe from NSE...")
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AlphaZero/5.0",
            "Referer": "https://www.nseindia.com"
        }
        r = requests.get(NSE_NIFTY500_URL, headers=headers, timeout=15)
        r.raise_for_status()
        
        reader = csv.DictReader(io.StringIO(r.text))
        symbols = []
        blacklist = {"ABGSHIP", "VIDEOIND", "SINTEX", "RELINFRA", "ADANITRANS"} # Delisted/Renamed/Problematic
        for row in reader:
            s = (row.get('Symbol') or row.get('SYMBOL') or "").strip()
            if s and s not in blacklist:
                symbols.append(s)
            
        if len(symbols) > 100:
            with open(CACHE_PATH, 'w') as f:
                json.dump(symbols, f)
            logger.info(f"Successfully fetched {len(symbols)} symbols from NSE.")
            return symbols
            
    except Exception as e:
        logger.warning(f"Failed to fetch NIFTY 500 from NSE: {e}. Falling back to hardcoded liquid list.")

    # Absolute fallback (Top 100 Liquid NSE Stocks)
    return [
        "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK", "BHARTIARTL", "SBIN", "LICI", "ITC", "HINDUNILVR",
        "LT", "BAJFINANCE", "HCLTECH", "ADANIENT", "MARUTI", "SUNPHARMA", "AXISBANK", "KOTAKBANK", "TITAN",
        "ONGC", "ULTRACEMCO", "NTPC", "TATAMOTORS", "ADANIPORTS", "JSWSTEEL", "POWERGRID", "ASIANPAINT",
        "TATASTEEL", "COALINDIA", "BAJAJ-AUTO", "ADANIPOWER", "M&M", "NESTLEIND", "GRASIM", "BAJAJFINSV",
        "SIEMENS", "INDUSINDBK", "DLF", "BRITANNIA", "SBILIFE", "HAL", "BEL", "PFC", "RECLTD", "ADANIGREEN",
        "ADANITRANS", "HINDALCO", "BPCL", "VBL", "IOC", "CIPLA", "TRENT", "VEDL", "EICHERMOT", "TATACONSUM",
        "TVSMOTOR", "HDFCLIFE", "ZOMATO", "GAIL", "SHREECEM", "DRREDDY", "DLF", "GRASIM", "HAVELLS", "DIVISLAB",
        "APOLLOHOSP", "GODREJCP", "BAJAJHLDNG", "PIDILITIND", "CHOLAFIN", "INDIGO", "SRF", "DABUR", "AMBUJACEM",
        "SHREECEM", "POLYCAB", "LTIM", "ABB", "TATAPOWER", "JINDALSTEL", "HINDPETRO", "ACC", "TORNTPHARM",
        "MAXHEALTH", "PAGEIND", "COLPAL", "MUTHOOTFIN", "AUROPHARMA", "LUPIN", "BALKRISIND", "MRF", "PETRONET",
        "CONCOR", "UPL", "IGL", "MGL", "GUJGASLTD", "CUMMINSIND", "TIINDIA", "ASHOKLEY", "BHEL", "BOSCHLTD"
    ]

_cached_sector_map: Optional[Dict[str, str]] = None

def get_sector_map() -> Dict[str, str]:
    """
    Manage sector mapping. For now, we use a cached version, 
    but it can be extended to scrape Screener.in for all 500 stocks.
    """
    global _cached_sector_map
    if _cached_sector_map:
        return _cached_sector_map
        
    # ── Initial Keyword-Based Sector Mapping ──────────────────────────────────
    _SECTOR_KW: Dict[str, List[str]] = {
        "BANKING":  ["BANK","HDFC","ICICI","AXIS","KOTAK","INDUSIND","FEDERAL","IDFC","BANDHAN","PNB","CANARA","BARODA","UNION","CSBBANK"],
        "IT":       ["TCS","INFY","WIPRO","HCLT","TECHM","LTIM","MPHASIS","COFORGE","OFSS","KPIT","TATAELX","PERSISTENT","ZENSARTECH","MASTEK"],
        "PHARMA":   ["PHARMA","CIPLA","DRREDDY","DIVISLAB","SUNPHARMA","APOLLOHOSP","BIOCON","ALKEM","IPCALAB","TORNTPHARM","AUROPHARMA","GLENMARK","LUPIN","GRANULES"],
        "AUTO":     ["MARUTI","TATAMOTORS","M&M","BAJAJ","EICHER","HERO","TVS","ASHOK","ESCORTS","FORCEMOT"],
        "ENERGY":   ["NTPC","POWER","TATAPOWER","ADANIGREEN","ONGC","IOC","BPCL","GAIL","PFC","REC","OIL","HINDPETRO"],
        "METALS":   ["TATASTEEL","HINDALCO","JSWSTEEL","VEDL","HINDZINC","NATIONALUM","NMDC","SAIL","JINDALSTEL"],
        "FMCG":     ["HINDUNILVR","ITC","NESTLEIND","BRITANNIA","DABUR","MARICO","GODREJCP","COLPAL","TATACONSUM","VBL"],
        "FINANCE":  ["BAJFINANCE","BAJAJFINSV","CHOLAFIN","MUTHOOTFIN","LICSGFIN","MANAPPURAM","CANFINHOME","SHRIRAMFIN"],
        "INFRA":    ["LT","SIEMENS","ABB","BHEL","CUMMINSIND","THERMAX","VOLTAS","HAVELLS","POLYCAB","KEI"],
        "RE_REALTY": ["DLF","GODREJPROP","OBEROIRLTY","PHOENIXLTD","PRESTIGE","LODHA"],
        "CONSUMER": ["TITAN","DMART","ZOMATO","NYKAA","INDHOTEL","JUBLFOOD","DIXON"],
    }
    
    mapping = {}
    symbols = get_nifty500_symbols()
    for sym in symbols:
        su = sym.upper()
        found = False
        for sec, keywords in _SECTOR_KW.items():
            if any(k in su for k in keywords):
                mapping[sym] = sec
                found = True
                break
        if not found:
            mapping[sym] = "OTHER"
    
    _cached_sector_map = mapping
    return mapping


def get_sector(symbol: str) -> str:
    """Helper to get a single stock's sector."""
    return get_sector_map().get(symbol, "OTHER")


def get_karma_universe(msd) -> List[str]:
    """
    Generate a dynamic learning universe for KARMA:
    - Top 50 Gainers (Nifty 500)
    - Top 50 Losers (Nifty 500)
    - 100 Random stocks from Nifty 500
    Total: ~200 stocks.
    """
    import random
    all_syms = get_nifty500_symbols()
    if not all_syms:
        return []

    logger.info(f"Generating KARMA universe from {len(all_syms)} NIFTY 500 stocks...")
    
    # 1. Fetch performance data for all (batched 100 at a time for safety)
    performance = []
    batch_size = 100
    for i in range(0, len(all_syms), batch_size):
        batch = all_syms[i : i + batch_size]
        quotes = msd.get_bulk_quotes(batch)
        for sym, q in quotes.items():
            chg = q.get("change_pct", 0)
            performance.append((sym, chg))

    if not performance:
        logger.warning("No performance data found for training universe. Using random sample.")
        return random.sample(all_syms, min(200, len(all_syms)))

    # 2. Sort by performance
    performance.sort(key=lambda x: x[1], reverse=True)
    
    top_gainers = [x[0] for x in performance[:50]]
    top_losers  = [x[0] for x in performance[-50:]]
    
    # 3. Random 100 (excluding gainers/losers)
    used = set(top_gainers + top_losers)
    remaining = [s for s in all_syms if s not in used]
    random_sample = random.sample(remaining, min(100, len(remaining)))
    
    final_list = list(set(top_gainers + top_losers + random_sample))
    logger.info(f"KARMA Universe Ready: {len(final_list)} stocks ({len(top_gainers)} gainers, {len(top_losers)} losers, {len(random_sample)} random)")
    
    return final_list
