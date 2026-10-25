"""
src/data/universe.py  —  AlphaZero Capital
═══════════════════════════════════════════════════════════════════════════════
Centralized Stock Universe Management.

Dynamically fetches NIFTY 500 constituents from NSE (live CSV) and caches them.
Automatically validates symbols against yfinance and blacklists any that return
no data (delisted / renamed / suspended), so stale hardcoded lists are never used.

The 24-hour cache means NSE is only hit once per day max; the auto-blacklist
persists across restarts in data/cache/delisted_symbols.json.
"""

import io
import csv
import json
import logging
import time
import threading
import requests
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger("Universe")

# ── Paths ──────────────────────────────────────────────────────────────────────
ROOT       = Path(__file__).resolve().parents[2]
CACHE_DIR  = ROOT / "data" / "cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

UNIVERSE_CACHE    = CACHE_DIR / "nifty500_universe.json"   # live NSE symbol list
BLACKLIST_CACHE   = CACHE_DIR / "delisted_symbols.json"    # auto-detected bad tickers
SECTOR_MAP_CACHE  = CACHE_DIR / "nse_sector_map.json"      # NSE-provided industry mapping

# Cache TTL (seconds)
UNIVERSE_TTL  = 24 * 3600   # refresh universe from NSE once per day
BLACKLIST_TTL = 7 * 24 * 3600  # re-validate blacklisted symbols weekly

# NSE public CSV endpoints
NSE_NIFTY500_URL  = "https://archives.nseindia.com/content/indices/ind_nifty500list.csv"
NSE_NIFTY50_URL   = "https://archives.nseindia.com/content/indices/ind_nifty50list.csv"
NSE_NIFTY100_URL  = "https://archives.nseindia.com/content/indices/ind_nifty100list.csv"
NSE_NIFTY200_URL  = "https://archives.nseindia.com/content/indices/ind_nifty200list.csv"

# ── Thread-safe blacklist state ────────────────────────────────────────────────
_blacklist_lock = threading.Lock()
_blacklist: Dict[str, float] = {}   # symbol → epoch when it was blacklisted

def _load_blacklist() -> None:
    """Load the persisted auto-blacklist from disk."""
    global _blacklist
    with _blacklist_lock:
        try:
            if BLACKLIST_CACHE.exists():
                with open(BLACKLIST_CACHE, "r") as f:
                    _blacklist = json.load(f)
        except Exception:
            _blacklist = {}

def _save_blacklist() -> None:
    """Persist the auto-blacklist to disk."""
    with _blacklist_lock:
        try:
            with open(BLACKLIST_CACHE, "w") as f:
                json.dump(_blacklist, f, indent=2)
        except Exception as e:
            logger.debug("Failed to save blacklist: %s", e)

def add_to_blacklist(symbol: str) -> None:
    """Mark a symbol as delisted/invalid. Called by any component that gets a 404."""
    with _blacklist_lock:
        if symbol not in _blacklist:
            logger.info("Auto-blacklisting delisted/invalid symbol: %s", symbol)
            _blacklist[symbol] = time.time()
    _save_blacklist()

def is_blacklisted(symbol: str) -> bool:
    """Return True if symbol is blacklisted (and TTL has not expired)."""
    with _blacklist_lock:
        ts = _blacklist.get(symbol)
        if ts is None:
            return False
        if time.time() - ts > BLACKLIST_TTL:
            # TTL expired — remove and re-validate next time
            del _blacklist[symbol]
            _save_blacklist()
            return False
        return True

# Initialise blacklist on module load
_load_blacklist()


# ── NSE Fetch helpers ──────────────────────────────────────────────────────────
def _fetch_nse_csv(url: str, timeout: int = 15) -> Optional[str]:
    """
    Download a CSV from NSE archives.  NSE requires a browser-like User-Agent
    and a Referer header — without them the request is blocked (403/empty).
    """
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Referer": "https://www.nseindia.com",
    }
    try:
        r = requests.get(url, headers=headers, timeout=timeout)
        r.raise_for_status()
        return r.text
    except Exception as e:
        logger.warning("NSE fetch failed for %s: %s", url, e)
        return None


def _parse_nse_csv(text: str) -> List[Dict[str, str]]:
    """
    Parse an NSE constituent CSV.
    Returns a list of dicts with at least 'Symbol' and optionally 'Industry'.
    """
    rows = []
    try:
        reader = csv.DictReader(io.StringIO(text))
        for row in reader:
            sym = (row.get("Symbol") or row.get("SYMBOL") or "").strip().upper()
            industry = (
                row.get("Industry")
                or row.get("INDUSTRY")
                or row.get("Sector")
                or ""
            ).strip()
            if sym:
                rows.append({"symbol": sym, "industry": industry})
    except Exception as e:
        logger.warning("CSV parse error: %s", e)
    return rows


# ── Live yfinance validation ───────────────────────────────────────────────────
def validate_symbols_live(symbols: List[str], batch_size: int = 50) -> List[str]:
    """
    Probe yfinance in batches to remove any symbol that returns zero price data.
    Symbols that fail are automatically added to the persistent blacklist.

    Returns only the symbols that passed validation.
    """
    try:
        import yfinance as yf
    except ImportError:
        logger.warning("yfinance not installed — skipping live validation")
        return symbols

    valid = []
    failed = []
    for i in range(0, len(symbols), batch_size):
        batch = symbols[i : i + batch_size]
        tickers_str = " ".join(s + ".NS" for s in batch)
        try:
            # fast_info is lightweight — no full download needed
            data = yf.download(
                tickers_str,
                period="1d",
                interval="1d",
                progress=False,
                auto_adjust=True,
                group_by="ticker",
            )
            for sym in batch:
                ns_sym = sym + ".NS"
                try:
                    if len(batch) == 1:
                        # Single ticker returns a plain DataFrame
                        col = data.get("Close", data.get("close"))
                        ok = col is not None and not col.dropna().empty
                    else:
                        col = data.get(ns_sym, {}).get("Close") if hasattr(data.get(ns_sym, None), "get") else None
                        try:
                            col = data["Close"][ns_sym]
                        except Exception:
                            col = None
                        ok = col is not None and not col.dropna().empty
                    if ok:
                        valid.append(sym)
                    else:
                        failed.append(sym)
                        add_to_blacklist(sym)
                except Exception:
                    failed.append(sym)
                    add_to_blacklist(sym)
        except Exception as e:
            logger.debug("Batch validation error: %s", e)
            # If the batch call itself fails, keep all symbols (conservative)
            valid.extend(batch)
        # Brief pause between batches
        time.sleep(0.3)

    if failed:
        logger.info("Live validation removed %d delisted/invalid symbols: %s",
                    len(failed), failed[:20])
    logger.info("Live validation: %d / %d symbols are tradable", len(valid), len(symbols))
    return valid


# ── Main public API ────────────────────────────────────────────────────────────
def get_nifty500_symbols(use_cache: bool = True, validate: bool = False) -> List[str]:
    """
    Return the current NIFTY 500 symbol list from NSE.

    Strategy (in order):
    1. Return from 24-hour file cache if fresh.
    2. Download the live NSE CSV and cache it.
    3. Fall back to the last cached version (even if stale).
    4. Return the 100-stock liquid fallback if everything else fails.

    Args:
        use_cache: Honour the 24-hour file cache (default True).
        validate:  Run live yfinance probe to strip delisted symbols (default False,
                   since validation adds ~30s; enable for overnight refresh jobs).

    Returns:
        Deduplicated list of valid NSE symbols, blacklisted symbols removed.
    """
    symbols: List[str] = []
    sector_map: Dict[str, str] = {}

    # ── 1. Try file cache ──────────────────────────────────────────────────────
    if use_cache and UNIVERSE_CACHE.exists():
        try:
            with open(UNIVERSE_CACHE, "r") as f:
                cached = json.load(f)
            age = time.time() - cached.get("timestamp", 0)
            if age < UNIVERSE_TTL and len(cached.get("symbols", [])) > 100:
                symbols = cached["symbols"]
                sector_map = cached.get("sector_map", {})
                logger.debug(
                    "Using cached NIFTY 500 universe (%d symbols, %.1fh old)",
                    len(symbols), age / 3600,
                )
        except Exception:
            pass

    # ── 2. Download from NSE if cache miss / stale ─────────────────────────────
    if not symbols:
        logger.info("Fetching NIFTY 500 universe from NSE archives...")
        text = _fetch_nse_csv(NSE_NIFTY500_URL)
        if text:
            rows = _parse_nse_csv(text)
            for row in rows:
                sym = row["symbol"]
                ind = row["industry"]
                if sym:
                    symbols.append(sym)
                    if ind:
                        sector_map[sym] = ind

        if len(symbols) > 100:
            # Persist fresh universe
            try:
                with open(UNIVERSE_CACHE, "w") as f:
                    json.dump(
                        {"timestamp": time.time(), "symbols": symbols, "sector_map": sector_map},
                        f, indent=2,
                    )
                logger.info("Fetched and cached %d NIFTY 500 symbols from NSE", len(symbols))
            except Exception as e:
                logger.debug("Failed to write universe cache: %s", e)
        else:
            logger.warning("NSE fetch returned < 100 symbols — trying stale cache")
            # ── 3. Stale cache fallback ────────────────────────────────────────
            if UNIVERSE_CACHE.exists():
                try:
                    with open(UNIVERSE_CACHE, "r") as f:
                        cached = json.load(f)
                    symbols = cached.get("symbols", [])
                    sector_map = cached.get("sector_map", {})
                    logger.info("Using stale cache with %d symbols", len(symbols))
                except Exception:
                    pass

    # ── 4. Last resort: hardcoded liquid 100 ──────────────────────────────────
    if len(symbols) < 50:
        logger.warning("All NSE fetch methods failed — using liquid-100 fallback list")
        symbols = _LIQUID_100_FALLBACK

    # ── Strip blacklisted (delisted / renamed) symbols ─────────────────────────
    before = len(symbols)
    symbols = [s for s in symbols if not is_blacklisted(s)]
    dropped = before - len(symbols)
    if dropped:
        logger.info("Dropped %d blacklisted symbols from universe", dropped)

    # Deduplicate while preserving order
    seen = set()
    symbols = [s for s in symbols if not (s in seen or seen.add(s))]

    # ── Optional live yfinance validation ─────────────────────────────────────
    if validate:
        logger.info("Running live yfinance validation on %d symbols...", len(symbols))
        symbols = validate_symbols_live(symbols)

    return symbols


def get_nifty50_symbols(use_cache: bool = True) -> List[str]:
    """
    Return the NIFTY 50 index symbols (top-50 liquid large-caps).
    Falls back to a filtered subset of the Nifty 500 list.
    """
    logger.info("Fetching NIFTY 50 universe from NSE archives...")
    text = _fetch_nse_csv(NSE_NIFTY50_URL)
    if text:
        rows = _parse_nse_csv(text)
        syms = [r["symbol"] for r in rows if r["symbol"] and not is_blacklisted(r["symbol"])]
        if len(syms) >= 40:
            logger.info("Fetched %d NIFTY 50 symbols", len(syms))
            return syms

    # Fallback: first 50 from Nifty 500
    logger.warning("NIFTY 50 fetch failed — slicing from NIFTY 500 list")
    return get_nifty500_symbols()[:50]


def get_nse_sector_map() -> Dict[str, str]:
    """
    Return a mapping of {symbol: NSE_industry_string} sourced from the Nifty 500 CSV.
    If the universe cache has sector data, use it; otherwise fetch fresh.
    """
    if UNIVERSE_CACHE.exists():
        try:
            with open(UNIVERSE_CACHE, "r") as f:
                cached = json.load(f)
            sm = cached.get("sector_map", {})
            if sm:
                return sm
        except Exception:
            pass
    # Trigger a fresh fetch which populates sector_map
    get_nifty500_symbols(use_cache=False)
    try:
        with open(UNIVERSE_CACHE, "r") as f:
            return json.load(f).get("sector_map", {})
    except Exception:
        return {}


def get_sector_map() -> Dict[str, str]:
    """
    Return {symbol: broad_sector} using keyword matching against NSE industry strings.
    The broad_sector values align with config/sectors.py sector names.
    Falls back to 'OTHER' for unmapped symbols.
    """
    global _cached_sector_map
    if _cached_sector_map:
        return _cached_sector_map

    # NSE NIFTY 500 CSV uses these exact industry strings (lowercased for matching).
    # Order matters — more specific entries must come before broader ones
    # to avoid false matches (e.g. "financial services" before "services").
    #
    # Real NSE industry strings found in ind_nifty500list.csv (Oct 2026):
    #   "Financial Services", "Information Technology", "Healthcare",
    #   "Fast Moving Consumer Goods", "Automobile And Auto Components",
    #   "Oil Gas & Consumable Fuels", "Metals & Mining", "Power",
    #   "Capital Goods", "Construction", "Construction Materials",
    #   "Consumer Durables", "Consumer Services", "Telecommunication",
    #   "Realty", "Chemicals", "Textiles", "Media Entertainment & Publication",
    #   "Diversified", "Services"
    _INDUSTRY_TO_SECTOR: Dict[str, str] = {
        # Banking — NSE groups banks inside "Financial Services" but we keep a
        # separate bucket.  Individual bank symbols are seeded in config/sectors.py
        # fallback; this keyword catches any sub-string that mentions bank explicitly.
        "bank": "BANKING",

        # IT / Technology
        "information technology": "IT",
        "software": "IT",

        # Healthcare / Pharma
        "healthcare": "PHARMA",
        "pharmaceut": "PHARMA",
        "hospital": "PHARMA",
        "medical": "PHARMA",
        "diagnostic": "PHARMA",

        # Auto
        "automobile and auto components": "AUTO",
        "automobile": "AUTO",
        "auto component": "AUTO",
        "tyre": "AUTO",

        # Energy / Oil & Gas / Power
        "oil gas": "ENERGY",
        "oil & gas": "ENERGY",
        "consumable fuel": "ENERGY",
        "power": "ENERGY",
        "petroleum": "ENERGY",
        "coal": "ENERGY",

        # Metals & Mining
        "metals & mining": "METALS",
        "metals and mining": "METALS",
        "steel": "METALS",
        "metal": "METALS",
        "mining": "METALS",
        "alumin": "METALS",
        "zinc": "METALS",

        # FMCG
        "fast moving consumer goods": "FMCG",
        "fmcg": "FMCG",
        "beverage": "FMCG",
        "tobacco": "FMCG",

        # Finance / NBFC / Insurance (catch-all — must come AFTER "bank" and "fmcg")
        "financial services": "FINANCE",
        "insurance": "FINANCE",
        "housing finance": "FINANCE",

        # Infrastructure / Capital Goods / Construction
        "capital goods": "INFRA",
        "construction materials": "INFRA",
        "construction": "INFRA",
        "cement": "INFRA",
        "infrastructure": "INFRA",

        # Consumer Durables / Services / Retail (discretionary)
        "consumer durables": "CONSUMER",
        "consumer services": "CONSUMER",
        "realty": "CONSUMER",
        "hotel": "CONSUMER",
        "retail": "CONSUMER",
        "textile": "CONSUMER",

        # Telecom / Media
        "telecommunication": "TELECOM",
        "media entertainment": "TELECOM",
        "media": "TELECOM",
    }

    nse_map  = get_nse_sector_map()   # {symbol: raw_industry_string_from_nse}
    symbols  = get_nifty500_symbols()

    # Known bank symbols — NSE classifies these as "Financial Services" but
    # we split them into BANKING for better sector diversification in trading.
    _KNOWN_BANKS = {
        "HDFCBANK", "ICICIBANK", "SBIN", "KOTAKBANK", "AXISBANK", "INDUSINDBK",
        "BANDHANBNK", "FEDERALBNK", "IDFCFIRSTB", "PNB", "CANBK", "BANKBARODA",
        "UNIONBANK", "INDIANB", "CSBBANK", "DCBBANK", "KARURVYSYA", "RBLBANK",
        "YESBANK", "SOUTHBANK", "TMBBANK", "UJJIVANSFB", "EQUITASBNK", "SURYODAY",
        "AUBANK", "JKBANK", "LAKSHVILAS", "SYNDIBANK", "ALLAHABAD",
    }

    mapping: Dict[str, str] = {}

    for sym in symbols:
        # Bank symbols get BANKING regardless of NSE industry classification
        if sym in _KNOWN_BANKS:
            mapping[sym] = "BANKING"
            continue

        raw_ind = nse_map.get(sym, "").lower()
        sector  = "OTHER"
        for keyword, broad in _INDUSTRY_TO_SECTOR.items():
            if keyword in raw_ind:
                sector = broad
                break
        mapping[sym] = sector

    _cached_sector_map = mapping
    return mapping


_cached_sector_map: Optional[Dict[str, str]] = None


def get_sector(symbol: str) -> str:
    """Return broad sector for a given NSE symbol, or 'OTHER' if unknown."""
    return get_sector_map().get(symbol.upper(), "OTHER")


def get_karma_universe(msd) -> List[str]:
    """
    Generate a dynamic learning universe for the KARMA RL agent:
      - Top 50 daily gainers from Nifty 500
      - Bottom 50 daily losers from Nifty 500
      - 100 random stocks from remaining pool
    Total ≈ 200 stocks, no blacklisted symbols included.
    """
    import random

    all_syms = get_nifty500_symbols()
    if not all_syms:
        return []

    logger.info("Generating KARMA universe from %d NIFTY 500 stocks...", len(all_syms))

    performance = []
    batch_size  = 50
    for i in range(0, len(all_syms), batch_size):
        batch  = all_syms[i : i + batch_size]
        quotes = msd.get_bulk_quotes(batch)
        for sym, q in quotes.items():
            chg = q.get("change_pct", 0) or 0
            performance.append((sym, chg))
        if i + batch_size < len(all_syms):
            time.sleep(0.3)

    if not performance:
        logger.warning("No performance data for training universe — using random sample.")
        return random.sample(all_syms, min(200, len(all_syms)))

    performance.sort(key=lambda x: x[1], reverse=True)
    top_gainers = [x[0] for x in performance[:50]]
    top_losers  = [x[0] for x in performance[-50:]]

    used      = set(top_gainers + top_losers)
    remaining = [s for s in all_syms if s not in used]
    random_sample = random.sample(remaining, min(100, len(remaining)))

    final = list(set(top_gainers + top_losers + random_sample))
    logger.info(
        "KARMA Universe: %d stocks (%d gainers, %d losers, %d random)",
        len(final), len(top_gainers), len(top_losers), len(random_sample),
    )
    return final


# ── Liquid-100 fallback (only used if NSE is completely unreachable) ───────────
# This list uses current (2026) NSE symbols — no delisted names.
_LIQUID_100_FALLBACK: List[str] = [
    # Banking
    "HDFCBANK", "ICICIBANK", "SBIN", "KOTAKBANK", "AXISBANK", "INDUSINDBK",
    "BANDHANBNK", "FEDERALBNK", "IDFCFIRSTB", "PNB", "CANBK", "BANKBARODA",
    # IT
    "TCS", "INFY", "HCLTECH", "WIPRO", "TECHM", "LTIM", "MPHASIS", "COFORGE",
    "PERSISTENT", "OFSS",
    # Large-Cap Diversified
    "RELIANCE", "LT", "BHARTIARTL", "ITC", "HINDUNILVR", "BAJFINANCE", "TITAN",
    "ASIANPAINT", "MARUTI", "NESTLEIND", "ULTRACEMCO", "ADANIPORTS", "ADANIENT",
    "ADANIGREEN", "ADANIPOWER",
    # Pharma / Healthcare
    "SUNPHARMA", "DRREDDY", "CIPLA", "DIVISLAB", "APOLLOHOSP", "BIOCON",
    "TORNTPHARM", "LUPIN", "AUROPHARMA", "ALKEM",
    # Auto
    "BAJAJ-AUTO", "HEROMOTOCO", "EICHERMOT", "TVSMOTOR", "M&M", "TATAMOTORS",
    # Energy / Oil & Gas
    "ONGC", "NTPC", "POWERGRID", "BPCL", "IOC", "GAIL", "TATAPOWER",
    "HINDPETRO", "PFC", "RECLTD",
    # Metals
    "TATASTEEL", "JSWSTEEL", "HINDALCO", "VEDL", "HINDZINC", "NATIONALUM",
    "NMDC", "SAIL", "JINDALSTEL",
    # FMCG
    "BRITANNIA", "DABUR", "MARICO", "GODREJCP", "COLPAL", "TATACONSUM", "VBL",
    # Finance / NBFC
    "BAJAJFINSV", "CHOLAFIN", "MUTHOOTFIN", "SHRIRAMFIN", "SBILIFE", "HDFCLIFE",
    # Infra / Capital Goods
    "SIEMENS", "ABB", "BHEL", "HAVELLS", "POLYCAB", "CUMMINSIND",
    # Consumer / Retail
    "ZOMATO", "TRENT", "NYKAA", "DLF", "INDIGO", "GODREJPROP",
]
