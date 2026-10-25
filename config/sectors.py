"""
config/sectors.py  —  AlphaZero Capital
════════════════════════════════════════════════════════════════════════════════
Sector mapping for NSE equities.

All sector data is now sourced dynamically from the NSE NIFTY 500 CSV
via src.data.universe.  There are NO hardcoded stock lists here — that
was the root cause of errors when NSE delists or renames a symbol.

The module still exposes the same public API as before:
    SECTORS          : dict[str, list[str]]
    SYMBOL_TO_SECTOR : dict[str, str]
    get_sector(sym)  -> str
    get_symbols_in_sector(sector) -> list[str]
"""

from __future__ import annotations

import json
import logging
import os
from typing import Dict, List

logger = logging.getLogger("Sectors")

# ── Load dynamic mapping from universe module ──────────────────────────────────
# This is done once at import time.  The universe module caches the NSE CSV for
# 24 hours, so there is no repeated network I/O on every import.

def _build_from_universe() -> tuple[Dict[str, List[str]], Dict[str, str]]:
    """
    Build SECTORS and SYMBOL_TO_SECTOR from the live NSE universe.
    Returns (SECTORS, SYMBOL_TO_SECTOR).
    """
    try:
        from src.data.universe import get_nifty500_symbols, get_sector_map
        symbols      = get_nifty500_symbols(use_cache=True)
        sector_lookup = get_sector_map()   # {symbol: broad_sector}

        sectors: Dict[str, List[str]] = {}
        for sym in symbols:
            sec = sector_lookup.get(sym, "OTHER")
            sectors.setdefault(sec, []).append(sym)

        sym_to_sec = {sym: sec for sec, syms in sectors.items() for sym in syms}
        logger.info(
            "Sectors loaded: %d symbols across %d sectors (NSE dynamic)",
            len(sym_to_sec), len(sectors),
        )
        return sectors, sym_to_sec

    except Exception as exc:
        logger.warning("Dynamic sector build failed (%s) — using minimal seed", exc)
        # Minimal seed using only confirmed-current (2026) NSE symbols
        seed: Dict[str, List[str]] = {
            "BANKING":  ["HDFCBANK", "ICICIBANK", "SBIN", "KOTAKBANK", "AXISBANK",
                         "INDUSINDBK", "BANDHANBNK", "FEDERALBNK", "IDFCFIRSTB",
                         "PNB", "CANBK", "BANKBARODA"],
            "IT":       ["TCS", "INFY", "HCLTECH", "WIPRO", "TECHM", "LTIM",
                         "MPHASIS", "COFORGE", "PERSISTENT", "OFSS"],
            "PHARMA":   ["SUNPHARMA", "DRREDDY", "CIPLA", "DIVISLAB", "APOLLOHOSP",
                         "BIOCON", "TORNTPHARM", "LUPIN", "AUROPHARMA", "ALKEM"],
            "AUTO":     ["MARUTI", "M&M", "BAJAJ-AUTO", "TVSMOTOR", "EICHERMOT",
                         "HEROMOTOCO", "ASHOKLEY", "TIINDIA", "BALKRISIND"],
            "ENERGY":   ["RELIANCE", "ONGC", "NTPC", "POWERGRID", "BPCL",
                         "IOC", "GAIL", "TATAPOWER", "HINDPETRO", "PFC", "RECLTD",
                         "ADANIGREEN", "ADANIPOWER"],
            "METALS":   ["TATASTEEL", "JSWSTEEL", "HINDALCO", "VEDL", "HINDZINC",
                         "NATIONALUM", "NMDC", "SAIL", "JINDALSTEL"],
            "FMCG":     ["HINDUNILVR", "ITC", "NESTLEIND", "BRITANNIA", "DABUR",
                         "MARICO", "GODREJCP", "COLPAL", "TATACONSUM", "VBL"],
            "FINANCE":  ["BAJFINANCE", "BAJAJFINSV", "CHOLAFIN", "MUTHOOTFIN",
                         "SHRIRAMFIN", "SBILIFE", "HDFCLIFE", "LICI"],
            "INFRA":    ["LT", "ULTRACEMCO", "GRASIM", "ADANIPORTS", "SIEMENS",
                         "ABB", "BHEL", "CUMMINSIND", "HAVELLS", "POLYCAB"],
            "CONSUMER": ["TITAN", "ASIANPAINT", "ZOMATO", "TRENT", "DLF",
                         "GODREJPROP", "INDIGO", "JUBLFOOD", "NYKAA"],
            "TELECOM":  ["BHARTIARTL", "INDUSTOWER"],
            "OTHER":    [],
        }
        s2s = {sym: sec for sec, syms in seed.items() for sym in syms}
        return seed, s2s


SECTORS, SYMBOL_TO_SECTOR = _build_from_universe()


# ── Merge overrides from dynamic_watchlist.json (if present) ──────────────────
_WATCHLIST_PATH = os.path.join(os.path.dirname(__file__), "dynamic_watchlist.json")
try:
    if os.path.exists(_WATCHLIST_PATH):
        with open(_WATCHLIST_PATH, "r") as _f:
            _dynamic = json.load(_f)
        for _sector, _symbols in _dynamic.items():
            _sec_upper = _sector.upper()
            SECTORS.setdefault(_sec_upper, [])
            for _sym in _symbols:
                if _sym not in SECTORS[_sec_upper]:
                    SECTORS[_sec_upper].append(_sym)
                SYMBOL_TO_SECTOR[_sym] = _sec_upper
        logger.debug("Dynamic watchlist merged into sector map (%s)", _WATCHLIST_PATH)
except Exception as _e:
    logger.debug("Failed to merge dynamic watchlist: %s", _e)


# ── Public API ─────────────────────────────────────────────────────────────────

def get_sector(symbol: str) -> str:
    """Return the broad sector for a given NSE symbol, or 'OTHER' if unknown."""
    return SYMBOL_TO_SECTOR.get(symbol.upper(), SYMBOL_TO_SECTOR.get(symbol, "OTHER"))


def get_symbols_in_sector(sector: str) -> List[str]:
    """Return all symbols currently mapped to the given sector."""
    return SECTORS.get(sector.upper(), [])


def refresh_sectors() -> None:
    """
    Force a live re-fetch of the NSE universe and rebuild all sector maps.
    Useful after nightly symbol refresh or when new stocks are added to NIFTY 500.
    """
    global SECTORS, SYMBOL_TO_SECTOR
    # Invalidate universe cache to force re-download
    try:
        from src.data.universe import UNIVERSE_CACHE, _cached_sector_map
        import src.data.universe as _uni
        _uni._cached_sector_map = None  # clear in-memory cache
        if UNIVERSE_CACHE.exists():
            UNIVERSE_CACHE.unlink()
    except Exception:
        pass
    SECTORS, SYMBOL_TO_SECTOR = _build_from_universe()
    logger.info("Sectors refreshed: %d sectors, %d symbols", len(SECTORS), len(SYMBOL_TO_SECTOR))
