"""
src/data/market_data.py  —  AlphaZero Capital v2
══════════════════════════════════════════════════
Multi-source market data engine for NSE stocks.

Data Source Priority (live quotes):
  1. OpenAlgo      — broker-grade real-time (MODE=LIVE)
  2. yfinance      — Yahoo Finance fast_info (free, ~15min delay)
  3. Stooq         — stooq.com CSV (free, EOD/delayed)
  4. NSE Bhav Copy — nseindia.com bulk CSV (EOD, free, no key)

Data Source Priority (historical candles):
  1. Cache         — SQLite/Parquet local cache (reused automatically)
  2. OpenAlgo      — if OPENALGO_KEY set
  3. yfinance      — best free source for intraday (60-day limit)
  4. Alpha Vantage — 25 req/day free tier (ALPHA_VANTAGE_KEY)
  5. Stooq         — daily candles, unlimited history

Fundamentals:
  1. Cache (7-day TTL)
  2. Screener.in   — P/E, ROE, debt (scraper, no API key needed)
  3. yfinance      — info dict fallback

FIXES v2:
  - yfinance MultiIndex columns bug: fixed with df.droplevel(1, axis=1)
  - yfinance rate-limit: exponential backoff retry (3x)
  - yfinance Ticker.fast_info KeyError: safe .get() wrapper
  - Historical data stored in SQLite+Parquet cache (data/cache/)
  - NSE Bhav Copy: fully implemented (was a stub)
  - NSEpy: direct NSE API support (no rate limits, faster)
  - Screener.in: P/E, ROE, D/E ratio scraper
  - next_market_open() function (backend.py dependency)
  - AV_AVAILABLE guard with 3 env var name variants
"""

from __future__ import annotations

import os, io, time, logging, threading, requests as _req
from datetime import datetime, timedelta, date
from dataclasses import dataclass, asdict
from typing import Optional, List, Dict, Any

try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo

import pandas as pd
import numpy as np

from src.data.cache import (
    save_ohlcv, load_ohlcv,
    save_fundamentals, load_fundamentals,
    cache_stats
)

logger = logging.getLogger("MarketData")
IST = ZoneInfo("Asia/Kolkata")

# ── Optional deps ─────────────────────────────────────────────────────────────
try:
    import yfinance as yf
    YF_AVAILABLE = True
except ImportError:
    YF_AVAILABLE = False
    logger.warning("yfinance not installed — pip install yfinance")

try:
    import requests as req
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False

try:
    from bs4 import BeautifulSoup
    BS4_AVAILABLE = True
except ImportError:
    BS4_AVAILABLE = False

# ── API Keys & Flags ──────────────────────────────────────────────────────────
OPENALGO_KEY  = os.getenv('OPENALGO_API_KEY', os.getenv('OPENALGO_KEY', ''))
OPENALGO_HOST = os.getenv('OPENALGO_URL', 'http://127.0.0.1:5000')
OA_AVAILABLE  = bool(OPENALGO_KEY and REQUESTS_AVAILABLE)

_AV_KEY       = os.getenv('ALPHA_VANTAGE_KEY',
                    os.getenv('ALPHAVANTAGE_API_KEY',
                    os.getenv('ALPHA_VANTAGE_API_KEY', '')))
AV_AVAILABLE  = bool(_AV_KEY and REQUESTS_AVAILABLE)

NSE_SUFFIX = ".NS"

# ── Market Hours ──────────────────────────────────────────────────────────────

def is_market_open(now: Optional[datetime] = None) -> bool:
    if now is None:
        now = datetime.now(tz=IST)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=IST)
    if now.weekday() >= 5:
        return False
    market_open  = now.replace(hour=9,  minute=15, second=0, microsecond=0)
    market_close = now.replace(hour=15, minute=30, second=0, microsecond=0)
    return market_open <= now <= market_close

def next_market_open(now: Optional[datetime] = None) -> datetime:
    """Return datetime of next NSE market open (09:15 IST)."""
    if now is None:
        now = datetime.now(tz=IST)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=IST)
    candidate = now.replace(hour=9, minute=15, second=0, microsecond=0)
    if now >= candidate:
        candidate += timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate += timedelta(days=1)
    return candidate


# ── CandleBar dataclass ───────────────────────────────────────────────────────

@dataclass
class CandleBar:
    symbol:   str
    datetime: datetime
    open:     float
    high:     float
    low:      float
    close:    float
    volume:   float
    source:   str = "unknown"

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d['datetime'] = self.datetime.isoformat() if isinstance(self.datetime, datetime) else str(self.datetime)
        for k in ('open','high','low','close','volume'):
            v = d[k]
            if v is None or (isinstance(v, float) and np.isnan(v)):
                d[k] = 0.0
        return d


# ── yfinance helpers (bug fixes) ──────────────────────────────────────────────

def _yf_fix_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    FIX: yfinance >= 0.2.x returns MultiIndex columns like
         ('Open', 'RELIANCE.NS') — flatten to lowercase single-level.
    """
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [col[0].lower() for col in df.columns]
    else:
        df.columns = [c.lower() for c in df.columns]
    return df

def _yf_download(symbol: str, start: str, end: str,
                  interval: str = "1d", retries: int = 3) -> Optional[pd.DataFrame]:
    """
    FIX: Wrap yfinance.download with:
      1. MultiIndex column flatten
      2. Exponential backoff retry on rate-limit (429 / JSONDecodeError)
      3. Adds .NS suffix for NSE if missing
      4. Returns None on failure instead of crashing
    """
    if not YF_AVAILABLE:
        return None
    ticker = symbol if symbol.endswith(".NS") else symbol + ".NS"
    for attempt in range(retries):
        try:
            df = yf.download(ticker, start=start, end=end,
                             interval=interval, progress=False, auto_adjust=True)
            if df is None or df.empty:
                return None
            df = _yf_fix_columns(df)
            # Ensure required columns exist
            for col in ('open','high','low','close','volume'):
                if col not in df.columns:
                    return None
            df = df[['open','high','low','close','volume']].copy()
            df.index = pd.to_datetime(df.index)
            df['datetime'] = df.index
            df['symbol']   = symbol
            df['source']   = 'yfinance'
            return df.reset_index(drop=True)
        except Exception as e:
            wait = 2 ** attempt
            logger.warning(f"yfinance attempt {attempt+1}/{retries} failed for {symbol}: {e} — retrying in {wait}s")
            time.sleep(wait)
    return None

def _yf_fast_quote(symbol: str) -> Optional[Dict]:
    """
    FIX: yfinance fast_info KeyError — use safe .get() on all fields.
    Returns {price, change_pct, volume, market_cap} or None.
    """
    if not YF_AVAILABLE:
        return None
    ticker = symbol if symbol.endswith(".NS") else symbol + ".NS"
    try:
        t  = yf.Ticker(ticker)
        fi = t.fast_info
        price = getattr(fi, 'last_price', None) or getattr(fi, 'regularMarketPrice', None)
        if price is None:
            return None
        prev  = getattr(fi, 'previous_close', None) or price
        vol   = getattr(fi, 'last_volume', None) or 0
        mcap  = getattr(fi, 'market_cap', None) or 0
        chg   = round((price - prev) / prev * 100, 2) if prev else 0.0
        return {
            'price':      round(float(price), 2),
            'change_pct': chg,
            'volume':     int(vol),
            'market_cap': int(mcap),
            'source':     'yfinance',
        }
    except Exception as e:
        logger.debug(f"yfinance fast_info failed {symbol}: {e}")
        return None


# ── NSE Bhav Copy (EOD bulk download) ────────────────────────────────────────

_BHAV_CACHE: Dict[date, pd.DataFrame] = {}

def fetch_nse_bhav(trade_date: Optional[date] = None) -> Optional[pd.DataFrame]:
    """
    Download NSE Bhav Copy CSV for given date.
    URL: https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_{DDMMYYYY}_F_0000.csv

    Returns DataFrame with columns: symbol, open, high, low, close, volume
    Cached in memory per session.
    """
    if trade_date is None:
        trade_date = date.today()

    if trade_date in _BHAV_CACHE:
        return _BHAV_CACHE[trade_date]

    date_str = trade_date.strftime("%d%m%Y")
    url = (
        f"https://nsearchives.nseindia.com/content/cm/"
        f"BhavCopy_NSE_CM_0_0_0_{date_str}_F_0000.csv"
    )
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "text/html,*/*",
        "Referer": "https://www.nseindia.com/",
    }
    try:
        r = _req.get(url, headers=headers, timeout=15)
        r.raise_for_status()
        df = pd.read_csv(io.StringIO(r.text))
        # Normalise column names
        df.columns = [c.strip().lower().replace(" ","_") for c in df.columns]
        # Common column mappings across NSE bhav formats
        col_map = {
            'tckrsymbl': 'symbol', 'symbol': 'symbol',
            'openpric':  'open',   'open_price': 'open',   'open': 'open',
            'highpric':  'high',   'high_price': 'high',   'high': 'high',
            'lowpric':   'low',    'low_price':  'low',    'low':  'low',
            'closepric': 'close',  'close_price':'close',  'close':'close',
            'ttlqdty':   'volume', 'total_traded_quantity': 'volume', 'volume': 'volume',
        }
        df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})
        required = ['symbol','open','high','low','close']
        if not all(c in df.columns for c in required):
            logger.warning(f"NSE Bhav: unexpected columns {df.columns.tolist()}")
            return None
        if 'volume' not in df.columns:
            df['volume'] = 0
        df = df[['symbol','open','high','low','close','volume']].copy()
        for col in ['open','high','low','close','volume']:
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
        df['source'] = 'bhav_copy'
        _BHAV_CACHE[trade_date] = df
        logger.info(f"NSE Bhav: {len(df)} symbols loaded for {trade_date}")
        return df
    except Exception as e:
        logger.warning(f"NSE Bhav fetch failed for {trade_date}: {e}")
        return None


def get_bhav_quote(symbol: str) -> Optional[Dict]:
    """Get today's EOD price from NSE Bhav Copy."""
    df = fetch_nse_bhav()
    if df is None:
        return None
    row = df[df['symbol'] == symbol.upper()]
    if row.empty:
        return None
    r = row.iloc[0]
    prev = float(r['open']) if float(r['open']) > 0 else float(r['close'])
    chg  = round((float(r['close']) - prev) / prev * 100, 2) if prev else 0
    return {
        'price':      float(r['close']),
        'change_pct': chg,
        'volume':     int(r['volume']),
        'source':     'bhav_copy',
    }


# ── NSEpy / Direct NSE API ────────────────────────────────────────────────────

def _nse_historical(symbol: str, start: date, end: date) -> Optional[pd.DataFrame]:
    """
    Direct NSE India API — faster than yfinance, no rate limit.
    Uses https://www.nseindia.com/api/historical/cm/equity endpoint.
    Falls back silently on any error.
    """
    session = _req.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.nseindia.com/",
    })
    try:
        # Warm up session cookie
        session.get("https://www.nseindia.com", timeout=10)
        params = {
            "symbol":    symbol.upper(),
            "series":    "EQ",
            "from":      start.strftime("%d-%m-%Y"),
            "to":        end.strftime("%d-%m-%Y"),
            "dataType":  "priceVolumeDeliverable",
        }
        r = session.get(
            "https://www.nseindia.com/api/historical/cm/equity",
            params=params, timeout=20
        )
        data = r.json()
        records = data.get("data", [])
        if not records:
            return None
        rows = []
        for rec in records:
            try:
                rows.append({
                    'datetime': pd.to_datetime(rec.get('CH_TIMESTAMP', rec.get('TIMESTAMP', ''))),
                    'open':     float(rec.get('CH_OPENING_PRICE', rec.get('OPEN_PRICE', 0))),
                    'high':     float(rec.get('CH_TRADE_HIGH_PRICE', rec.get('HIGH_PRICE', 0))),
                    'low':      float(rec.get('CH_TRADE_LOW_PRICE', rec.get('LOW_PRICE', 0))),
                    'close':    float(rec.get('CH_CLOSING_PRICE', rec.get('CLOSE_PRICE', 0))),
                    'volume':   float(rec.get('CH_TOT_TRADED_QTY', rec.get('TOTAL_TRADED_QUANTITY', 0))),
                    'symbol':   symbol,
                    'source':   'nse_direct',
                })
            except Exception:
                continue
        if not rows:
            return None
        df = pd.DataFrame(rows).sort_values('datetime').reset_index(drop=True)
        logger.info(f"NSE Direct: {symbol} → {len(df)} rows")
        return df
    except Exception as e:
        logger.debug(f"NSE Direct API failed for {symbol}: {e}")
        return None


# ── Screener.in Fundamentals Scraper ─────────────────────────────────────────

_SCREENER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "text/html,application/xhtml+xml,*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.screener.in/",
}

def fetch_screener_fundamentals(symbol: str) -> Optional[Dict]:
    """
    Scrape P/E, P/B, ROE, D/E ratio and more from screener.in.
    No API key required. Cached for 7 days.

    Returns: {pe, pb, roe, debt_equity, market_cap, revenue, net_profit, eps,
              dividend, sector, industry}
    """
    # Try cache first
    cached = load_fundamentals(symbol)
    if cached:
        return cached

    if not BS4_AVAILABLE or not REQUESTS_AVAILABLE:
        return _yf_fundamentals(symbol)

    url = f"https://www.screener.in/company/{symbol.upper()}/consolidated/"
    try:
        r = _req.get(url, headers=_SCREENER_HEADERS, timeout=15)
        if r.status_code == 404:
            url = f"https://www.screener.in/company/{symbol.upper()}/"
            r   = _req.get(url, headers=_SCREENER_HEADERS, timeout=15)
        r.raise_for_status()

        soup = BeautifulSoup(r.text, 'html.parser')

        def _ratio(name: str) -> Optional[float]:
            """Find a ratio value by label text."""
            for li in soup.select('li.flex.flex-space-between'):
                label_tag = li.find('span', class_='name')
                val_tag   = li.find('span', class_='nowrap')
                if label_tag and val_tag:
                    label = label_tag.get_text(strip=True)
                    if name.lower() in label.lower():
                        raw = val_tag.get_text(strip=True).replace(',','').replace('%','').replace('₹','').strip()
                        try:
                            return float(raw)
                        except ValueError:
                            pass
            return None

        # Extract sector from breadcrumb
        sector_tag = soup.select_one('a[href*="/screen/"]')
        sector = sector_tag.get_text(strip=True) if sector_tag else ""

        data = {
            'pe':          _ratio('P/E'),
            'pb':          _ratio('Price to Book') or _ratio('P/B'),
            'roe':         _ratio('Return on equity') or _ratio('ROE'),
            'debt_equity': _ratio('Debt to equity') or _ratio('D/E'),
            'market_cap':  _ratio('Market Cap'),
            'revenue':     None,
            'net_profit':  None,
            'eps':         _ratio('EPS'),
            'dividend':    _ratio('Dividend Yield'),
            'sector':      sector,
            'industry':    "",
        }

        # Try to get revenue and net profit from financial summary table
        for table in soup.select('table.data-table'):
            headers = [th.get_text(strip=True) for th in table.select('thead th')]
            if 'Sales' in headers or 'Revenue' in headers:
                rows_data = table.select('tbody tr')
                for row in rows_data:
                    cols_data = [td.get_text(strip=True) for td in row.select('td')]
                    if cols_data and 'Net Profit' in cols_data[0]:
                        try:
                            data['net_profit'] = float(cols_data[-1].replace(',',''))
                        except Exception:
                            pass

        save_fundamentals(symbol, data)
        logger.info(f"Screener.in: {symbol} fundamentals cached")
        return data

    except Exception as e:
        logger.warning(f"Screener.in failed for {symbol}: {e}")
        return _yf_fundamentals(symbol)


def _yf_fundamentals(symbol: str) -> Optional[Dict]:
    """Fallback: get fundamentals from yfinance .info dict."""
    if not YF_AVAILABLE:
        return None
    try:
        ticker = symbol if symbol.endswith(".NS") else symbol + ".NS"
        info   = yf.Ticker(ticker).info or {}
        data = {
            'pe':          info.get('trailingPE'),
            'pb':          info.get('priceToBook'),
            'roe':         info.get('returnOnEquity'),
            'debt_equity': info.get('debtToEquity'),
            'market_cap':  info.get('marketCap'),
            'revenue':     info.get('totalRevenue'),
            'net_profit':  info.get('netIncomeToCommon'),
            'eps':         info.get('trailingEps'),
            'dividend':    info.get('dividendYield'),
            'sector':      info.get('sector', ''),
            'industry':    info.get('industry', ''),
        }
        save_fundamentals(symbol, data)
        return data
    except Exception as e:
        logger.debug(f"yfinance fundamentals failed {symbol}: {e}")
        return None


# ── OpenAlgo Live/Historical ──────────────────────────────────────────────────

def _oa_quote(symbol: str) -> Optional[Dict]:
    if not OA_AVAILABLE:
        return None
    try:
        r = _req.get(
            f"{OPENALGO_HOST}/api/v1/quotes",
            params={"apikey": OPENALGO_KEY, "symbol": symbol, "exchange": "NSE"},
            timeout=5,
        )
        d = r.json()
        ltp = d.get("ltp") or d.get("last_price") or d.get("close")
        if ltp:
            return {'price': float(ltp), 'source': 'openalgo',
                    'change_pct': float(d.get('change_pct', 0))}
    except Exception as e:
        logger.debug(f"OpenAlgo quote failed {symbol}: {e}")
    return None

def _oa_historical(symbol: str, start: str, end: str, interval: str = "1d") -> Optional[pd.DataFrame]:
    if not OA_AVAILABLE:
        return None
    iv_map = {"1m":"1","5m":"5","15m":"15","1h":"60","1d":"1D"}
    oa_iv  = iv_map.get(interval, "1D")
    try:
        r = _req.post(
            f"{OPENALGO_HOST}/api/v1/history",
            json={"apikey": OPENALGO_KEY, "symbol": symbol,
                  "exchange": "NSE", "interval": oa_iv,
                  "start_date": start, "end_date": end},
            timeout=30,
        )
        records = r.json().get("data", [])
        if not records:
            return None
        df = pd.DataFrame(records)
        df.columns = [c.lower() for c in df.columns]
        if 'time' in df.columns and 'datetime' not in df.columns:
            df['datetime'] = pd.to_datetime(df['time'])
        elif 'date' in df.columns:
            df['datetime'] = pd.to_datetime(df['date'])
        df['symbol'] = symbol
        df['source'] = 'openalgo'
        return df[['datetime','open','high','low','close','volume','symbol','source']]
    except Exception as e:
        logger.debug(f"OpenAlgo history failed {symbol}: {e}")
    return None


# ── Alpha Vantage Historical ──────────────────────────────────────────────────

_AV_LAST_CALL = 0.0

def _av_historical(symbol: str, interval: str = "1d") -> Optional[pd.DataFrame]:
    if not AV_AVAILABLE:
        return None
    global _AV_LAST_CALL
    # Rate-limit: 12 req/min free tier → 5s gap
    wait = max(0, 5 - (time.time() - _AV_LAST_CALL))
    if wait:
        time.sleep(wait)
    _AV_LAST_CALL = time.time()

    iv_map = {"1m":"1min","5m":"5min","15m":"15min","1h":"60min","1d":"daily"}
    av_iv  = iv_map.get(interval, "daily")
    fn     = "TIME_SERIES_INTRADAY" if interval != "1d" else "TIME_SERIES_DAILY_ADJUSTED"
    params = {"function": fn, "symbol": f"{symbol}.BSE",
              "apikey": _AV_KEY, "datatype": "csv", "outputsize": "full"}
    if interval != "1d":
        params["interval"] = av_iv
    try:
        r  = _req.get("https://www.alphavantage.co/query", params=params, timeout=30)
        df = pd.read_csv(io.StringIO(r.text))
        if df.empty or 'timestamp' not in df.columns.str.lower().tolist():
            return None
        df.columns = [c.lower() for c in df.columns]
        df['datetime'] = pd.to_datetime(df.get('timestamp', df.get('date')))
        df = df.rename(columns={'adjusted_close': 'close'} if 'adjusted_close' in df.columns else {})
        df['symbol'] = symbol
        df['source'] = 'alpha_vantage'
        return df[['datetime','open','high','low','close','volume','symbol','source']].sort_values('datetime')
    except Exception as e:
        logger.debug(f"Alpha Vantage failed {symbol}: {e}")
    return None


# ── Stooq Historical ──────────────────────────────────────────────────────────

def _stooq_historical(symbol: str, start: str, end: str) -> Optional[pd.DataFrame]:
    """Stooq.com EOD data — free, no key, unlimited history."""
    stooq_sym = symbol.lower() + ".ns"
    url = (f"https://stooq.com/q/d/l/?s={stooq_sym}"
           f"&d1={start.replace('-','')}&d2={end.replace('-','')}&i=d")
    try:
        r  = _req.get(url, timeout=15)
        df = pd.read_csv(io.StringIO(r.text))
        if df.empty or len(df.columns) < 5:
            return None
        df.columns = [c.lower() for c in df.columns]
        df['datetime'] = pd.to_datetime(df['date'])
        df['symbol']   = symbol
        df['source']   = 'stooq'
        return df[['datetime','open','high','low','close','volume','symbol','source']].sort_values('datetime')
    except Exception as e:
        logger.debug(f"Stooq failed {symbol}: {e}")
    return None


# ── DataFetcher (main API used by agents) ─────────────────────────────────────

class DataFetcher:
    """
    Single interface for all market data needs.
    Used by all 16 agents via cfg['data_fetcher'].

    Usage:
        fetcher = DataFetcher(cfg)

        # Live quote
        quote = fetcher.get_quote("RELIANCE")   → {price, change_pct, volume}

        # Historical OHLCV (cached automatically)
        df = fetcher.get_historical("TCS", "2024-01-01", "2024-12-31", "1d")

        # Fundamentals (scraped from Screener.in, cached 7 days)
        fund = fetcher.get_fundamentals("INFY")

        # NSE Bhav Copy
        bhav = fetcher.get_bhav_copy()   → full DataFrame of all NSE stocks
    """

    def __init__(self, cfg: Optional[Dict] = None):
        self.cfg = cfg or {}

    # ── Live Quote ────────────────────────────────────────────────────────────
    def get_quote(self, symbol: str) -> Optional[Dict]:
        """
        Get live/latest price. Chain: OpenAlgo → yfinance → Bhav Copy.
        """
        # 1. OpenAlgo (MODE=LIVE only)
        mode = self.cfg.get('MODE', os.getenv('MODE', 'PAPER')).upper()
        if mode == 'LIVE':
            q = _oa_quote(symbol)
            if q:
                return q

        # 2. yfinance fast_info
        q = _yf_fast_quote(symbol)
        if q:
            return q

        # 3. NSE Bhav Copy (EOD fallback)
        q = get_bhav_quote(symbol)
        return q

    def get_quotes_batch(self, symbols: List[str]) -> Dict[str, Dict]:
        """Fetch multiple quotes efficiently using bhav copy where possible."""
        results = {}
        for sym in symbols:
            try:
                q = self.get_quote(sym)
                if q:
                    results[sym] = q
            except Exception as e:
                logger.debug(f"Quote failed {sym}: {e}")
        return results

    # ── Historical OHLCV ──────────────────────────────────────────────────────
    def get_historical(self, symbol: str,
                        start: str, end: str,
                        interval: str = "1d") -> Optional[pd.DataFrame]:
        """
        Get historical OHLCV. Checks cache first, then fetches and caches.
        Chain: Cache → OpenAlgo → NSE Direct → yfinance → Alpha Vantage → Stooq
        """
        # 1. Check local cache
        df = load_ohlcv(symbol, interval, start, end)
        if df is not None and not df.empty:
            logger.debug(f"Cache hit: {symbol} {interval}")
            return df

        # 2. OpenAlgo
        df = _oa_historical(symbol, start, end, interval)
        if df is not None and not df.empty:
            save_ohlcv(symbol, interval, df, start, end)
            return df

        # 3. NSE Direct API (daily only)
        if interval in ("1d", "D"):
            try:
                s = datetime.strptime(start, "%Y-%m-%d").date()
                e = datetime.strptime(end,   "%Y-%m-%d").date()
                df = _nse_historical(symbol, s, e)
                if df is not None and not df.empty:
                    save_ohlcv(symbol, interval, df, start, end)
                    return df
            except Exception:
                pass

        # 4. yfinance (with MultiIndex fix + retry)
        df = _yf_download(symbol, start, end, interval)
        if df is not None and not df.empty:
            save_ohlcv(symbol, interval, df, start, end)
            return df

        # 5. Alpha Vantage
        df = _av_historical(symbol, interval)
        if df is not None and not df.empty:
            # Filter to requested date range
            df = df[(df['datetime'] >= pd.Timestamp(start)) &
                    (df['datetime'] <= pd.Timestamp(end))]
            if not df.empty:
                save_ohlcv(symbol, interval, df, start, end)
                return df

        # 6. Stooq (daily only)
        if interval == "1d":
            df = _stooq_historical(symbol, start, end)
            if df is not None and not df.empty:
                save_ohlcv(symbol, interval, df, start, end)
                return df

        logger.warning(f"No data found for {symbol} {interval} {start}→{end}")
        return None

    # ── Fundamentals ──────────────────────────────────────────────────────────
    def get_fundamentals(self, symbol: str) -> Optional[Dict]:
        """Get P/E, ROE, D/E etc. from Screener.in (cached 7 days)."""
        return fetch_screener_fundamentals(symbol)

    # ── Bhav Copy ─────────────────────────────────────────────────────────────
    def get_bhav_copy(self, trade_date: Optional[date] = None) -> Optional[pd.DataFrame]:
        return fetch_nse_bhav(trade_date)

    # ── Cache Stats ───────────────────────────────────────────────────────────
    def cache_info(self) -> Dict:
        return cache_stats()

    # ── Live market feed (real-time polling) ──────────────────────────────────
    def start_live_feed(self, symbols: List[str],
                         callback,
                         interval_secs: int = 60) -> threading.Thread:
        """
        Start background thread that polls quotes every `interval_secs`
        and calls callback(symbol, quote_dict) for each update.

        Usage:
            def on_tick(sym, q):
                print(f"{sym}: ₹{q['price']}")
            fetcher.start_live_feed(['RELIANCE','TCS'], on_tick, 60)
        """
        def _poll():
            logger.info(f"Live feed started for {len(symbols)} symbols (every {interval_secs}s)")
            while True:
                if is_market_open():
                    for sym in symbols:
                        try:
                            q = self.get_quote(sym)
                            if q:
                                callback(sym, q)
                        except Exception as e:
                            logger.debug(f"Live feed error {sym}: {e}")
                    time.sleep(interval_secs)
                else:
                    time.sleep(60)  # Sleep during off-hours

        t = threading.Thread(target=_poll, daemon=True, name="LiveFeed")
        t.start()
        return t
