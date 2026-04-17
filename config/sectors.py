"""
NSE Sector Definitions
config/sectors.py

Moved from root sectors.py into config/ as per project structure.
All agents should import from config.sectors, not from root.
"""

SECTORS = {
    'BANKING':  ['HDFCBANK', 'ICICIBANK', 'KOTAKBANK', 'AXISBANK', 'SBIN'],
    'IT':       ['TCS', 'INFY', 'WIPRO', 'HCLTECH', 'TECHM'],
    'AUTO':     ['MARUTI', 'M&M', 'TATAMOTORS', 'BAJAJ-AUTO', 'HEROMOTOCO'],
    'PHARMA':   ['SUNPHARMA', 'DRREDDY', 'CIPLA', 'DIVISLAB', 'BIOCON'],
    'FMCG':     ['HINDUNILVR', 'ITC', 'NESTLEIND', 'BRITANNIA', 'DABUR'],
    'ENERGY':   ['RELIANCE', 'ONGC', 'NTPC', 'POWERGRID', 'COALINDIA'],
    'METALS':   ['TATASTEEL', 'HINDALCO', 'JSWSTEEL', 'VEDL', 'HINDZINC'],
    'INFRA':    ['LT', 'ULTRACEMCO', 'GRASIM', 'ADANIPORTS', 'SIEMENS'],
    'TELECOM':  ['BHARTIARTL', 'IDEA', 'INDUSTOWER'],
    'FINANCE':  ['BAJFINANCE', 'BAJAJFINSV', 'HDFC', 'MUTHOOTFIN', 'CHOLAFIN'],
}

import os
import json

# Load dynamic watchlist if it exists
_WATCHLIST_PATH = os.path.join(os.path.dirname(__file__), 'dynamic_watchlist.json')
try:
    if os.path.exists(_WATCHLIST_PATH):
        with open(_WATCHLIST_PATH, 'r') as f:
            dynamic_data = json.load(f)
            for sector, symbols in dynamic_data.items():
                sector_upper = sector.upper()
                if sector_upper in SECTORS:
                    for sym in symbols:
                        if sym not in SECTORS[sector_upper]:
                            SECTORS[sector_upper].append(sym)
                else:
                    SECTORS[sector_upper] = symbols
except Exception as e:
    print(f"[Warning] Failed to load dynamic watchlist: {e}")

# Flat reverse lookup: symbol → sector (built once at import time)
SYMBOL_TO_SECTOR = {
    symbol: sector
    for sector, symbols in SECTORS.items()
    for symbol in symbols
}


def get_sector(symbol: str) -> str:
    """Return the sector for a given NSE symbol, or 'OTHER' if unknown."""
    return SYMBOL_TO_SECTOR.get(symbol, 'OTHER')


def get_symbols_in_sector(sector: str):
    """Return all symbols in a given sector."""
    return SECTORS.get(sector.upper(), [])
