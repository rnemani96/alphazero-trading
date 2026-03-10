"""
src/data/market_data.py  —  AlphaZero Capital
═══════════════════════════════════════════════
Multi-source market data engine for NSE stocks.

Data Source Priority (live quotes):
  1. OpenAlgo      — broker-grade real-time (if OPENALGO_KEY is set)
  2. yfinance      — Yahoo Finance fast_info (free, ~15min delay)
  3. Stooq         — stooq.com CSV (free, EOD/delayed)
  4. NSE CSV       — nseindia.com bhav copy (free, EOD)

Data Source Priority (historical candles):
  1. OpenAlgo      — if OPENALGO_KEY is set
  2. yfinance      — best free source for intraday (60-day limit)
  3. Stooq         — daily candles, unlimited history (no intraday)
  4. Alpha Vantage — if ALPHA_VANTAGE_KEY is set (5 req/min free tier)

Set env vars:
  OPENALGO_HOST  = http://localhost:5000
  OPENALGO_KEY   = your-key
  ALPHA_VANTAGE_KEY = your-key          (optional)
"""

import os
import io
import time
import logging
import threading
from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

import pandas as pd
import numpy as np

logger = logging.getLogger("MarketData")

IST = ZoneInfo("Asia/Kolkata")

# ── Optional deps ──────────────────────────────────────────────────────────────
try:
    from nsepython import *
    NSE_PYTHON_AVAILABLE = True
except ImportError:
    NSE_PYTHON_AVAILABLE = False

try:
    import yfinance as yf
    YF_AVAILABLE = True
except ImportError:
    YF_AVAILABLE = False
    logger.warning("yfinance not installed. pip install yfinance")

try:
    import requests as req
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False
    logger.warning("requests not installed. pip install requests")

# ── Env config ────────────────────────────────────────────────────────────────
OPENALGO_HOST     = os.getenv("OPENALGO_HOST", "http://localhost:5000")
OPENALGO_KEY      = os.getenv("OPENALGO_KEY", "")
ALPHA_VANTAGE_KEY = os.getenv("ALPHA_VANTAGE_KEY", "")
OA_AVAILABLE      = bool(OPENALGO_KEY) and REQUESTS_AVAILABLE
AV_AVAILABLE      = bool(ALPHA_VANTAGE_KEY) and REQUESTS_AVAILABLE

# ── Symbol maps ───────────────────────────────────────────────────────────────
NSE_YAHOO_MAP = {
    "RELIANCE": "RELIANCE.NS", "TCS": "TCS.NS", "HDFCBANK": "HDFCBANK.NS",
    "INFY": "INFY.NS", "ICICIBANK": "ICICIBANK.NS", "SBIN": "SBIN.NS",
    "WIPRO": "WIPRO.NS", "TATAMOTORS": "TATAMOTORS.NS", "SUNPHARMA": "SUNPHARMA.NS",
    "MARUTI": "MARUTI.NS", "BAJFINANCE": "BAJFINANCE.NS", "AXISBANK": "AXISBANK.NS",
    "KOTAKBANK": "KOTAKBANK.NS", "HINDUNILVR": "HINDUNILVR.NS",
    "ASIANPAINT": "ASIANPAINT.NS", "TITAN": "TITAN.NS", "NTPC": "NTPC.NS",
    "POWERGRID": "POWERGRID.NS", "LTIM": "LTIM.NS", "ULTRACEMCO": "ULTRACEMCO.NS",
    "NIFTY50": "^NSEI", "BANKNIFTY": "^NSEBANK", "VIX": "^INDIAVIX",
    "BAJAJFINSV": "BAJAJFINSV.NS", "HCLTECH": "HCLTECH.NS", "ITC": "ITC.NS",
    "LT": "LT.NS", "M&M": "M%26M.NS", "ONGC": "ONGC.NS", "ADANIPORTS": "ADANIPORTS.NS",
    "COALINDIA": "COALINDIA.NS", "BPCL": "BPCL.NS", "DIVISLAB": "DIVISLAB.NS",
    "DRREDDY": "DRREDDY.NS", "EICHERMOT": "EICHERMOT.NS", "GRASIM": "GRASIM.NS",
    "HEROMOTOCO": "HEROMOTOCO.NS", "HINDALCO": "HINDALCO.NS", "JSWSTEEL": "JSWSTEEL.NS",
    "NESTLEIND": "NESTLEIND.NS", "SHREECEM": "SHREECEM.NS", "TATACONSUM": "TATACONSUM.NS",
    "TATASTEEL": "TATASTEEL.NS", "TECHM": "TECHM.NS", "ULIEMS": "ULTRACEMCO.NS",
}

# Stooq uses SYMBOL.NS format too (same as Yahoo for NSE)
def _yahoo_sym(symbol: str) -> str:
    return NSE_YAHOO_MAP.get(symbol.upper(), symbol.upper() + ".NS")

def _stooq_sym(symbol: str) -> str:
    """Stooq uses lowercase .ns suffix."""
    base = symbol.upper().replace("&", "%26")
    return NSE_YAHOO_MAP.get(symbol.upper(), symbol.upper() + ".NS").lower().replace(".ns", ".ns")


# ── CandleBar ─────────────────────────────────────────────────────────────────
class CandleBar:
    __slots__ = ["datetime", "open", "high", "low", "close", "volume"]

    def __init__(self, dt, o, h, l, c, v=0):
        self.datetime = dt if isinstance(dt, datetime) else pd.Timestamp(dt).to_pydatetime()
        self.open  = float(o);  self.high  = float(h)
        self.low   = float(l);  self.close = float(c)
        self.volume = int(v) if v else 0

    def to_dict(self):
        return {
            "datetime": self.datetime.isoformat(),
            "open": self.open, "high": self.high,
            "low":  self.low,  "close": self.close,
            "volume": self.volume,
        }


# ── Main engine ───────────────────────────────────────────────────────────────
class MarketDataEngine:
    """
    Unified data engine with 4-source fallback chain.
    All methods are thread-safe.
    """

    def __init__(self):
        self._hist_cache:   dict[str, list[CandleBar]] = {}
        self._quote_cache:  dict[str, dict]             = {}
        self._hist_ttl:     dict[str, float]            = {}  # key → expiry epoch
        self._quote_ttl:    dict[str, float]            = {}
        self._lock     = threading.Lock()
        self._running  = False
        self._subscribers: list = []
        self._poll_thread = None

        logger.info("MarketDataEngine init — sources: OA=%s YF=%s AV=%s STOOQ=yes",
                    OA_AVAILABLE, YF_AVAILABLE, AV_AVAILABLE)

    # ── Historical candles ────────────────────────────────────────────────────

    def fetch_historical(self, symbol: str, period: str = "3mo",
                         interval: str = "15m") -> list[CandleBar]:
        """
        Fetch OHLCV candles with 4-source fallback.
        interval intraday (< 1d): yfinance limited to last 60 days.
        interval daily (1d, 1wk): Stooq has unlimited history.
        """
        cache_key = f"{symbol}:{period}:{interval}"
        # Return cached if still fresh (5 min for intraday, 1h for daily)
        ttl = 300 if "m" in interval or "h" in interval else 3600
        with self._lock:
            if cache_key in self._hist_cache and time.time() < self._hist_ttl.get(cache_key, 0):
                return self._hist_cache[cache_key]

        candles = []

        # 1. nsepython
        if NSE_PYTHON_AVAILABLE:
            candles = self._nse_history(symbol, period, interval)
            if candles:
                logger.info("[NSE] %d candles for %s", len(candles), symbol)

        # 2. OpenAlgo
        if not candles and OA_AVAILABLE:
            candles = self._oa_history(symbol, period, interval)
            if candles:
                logger.info("[OA] %d candles for %s", len(candles), symbol)

        # 3. yfinance
        if not candles and YF_AVAILABLE:
            candles = self._yf_history(symbol, period, interval)
            if candles:
                logger.info("[YF] %d candles for %s", len(candles), symbol)

        # 4. Stooq (only supports daily; auto-downgrade)
        if not candles and REQUESTS_AVAILABLE:
            stooq_period = period
            stooq_interval = "1d" if interval not in ("1d", "1wk", "1mo") else interval
            candles = self._stooq_history(symbol, stooq_period)
            if candles:
                logger.info("[Stooq] %d daily candles for %s", len(candles), symbol)

        # 5. Alpha Vantage
        if not candles and AV_AVAILABLE:
            candles = self._av_history(symbol, interval)
            if candles:
                logger.info("[AV] %d candles for %s", len(candles), symbol)

        if not candles:
            logger.error("All sources exhausted for %s", symbol)
            return []

        with self._lock:
            self._hist_cache[cache_key] = candles
            self._hist_ttl[cache_key]   = time.time() + ttl

        return candles

    def _nse_history(self, symbol: str, period: str, interval: str) -> list[CandleBar]:
        """Fetch historical data using nsepython's nse_get_hist."""
        try:
            # Map period to days for nsepython
            period_days = {"1d":1,"5d":5,"1mo":30,"3mo":90,"6mo":180,"1y":365,"2y":730}
            days  = period_days.get(period, 90)
            end   = datetime.now()
            start = end - timedelta(days=days)
            
            df = nse_get_hist(symbol, start.strftime("%d-%m-%Y"), end.strftime("%d-%m-%Y"))
            if df is None or df.empty:
                return []
            
            # Standardize columns
            df.columns = [c.strip().upper() for c in df.columns]
            rename_map = {
                'DATE': 'datetime', 'OPEN': 'open', 'HIGH': 'high', 
                'LOW': 'low', 'CLOSE': 'close', 'VOLUME': 'volume'
            }
            for old_col in df.columns:
                for target, mapped in rename_map.items():
                    if target in old_col:
                        df.rename(columns={old_col: mapped}, inplace=True)
            
            result = []
            for _, row in df.iterrows():
                try:
                    dt = pd.to_datetime(row['datetime']).to_pydatetime()
                    result.append(CandleBar(dt, row['open'], row['high'], row['low'], row['close'], row.get('volume', 0)))
                except:
                    continue
            return result
        except Exception as e:
            logger.debug("nsepython history %s: %s", symbol, e)
            return []

    def _yf_history(self, symbol: str, period: str, interval: str) -> list[CandleBar]:
        ysym = _yahoo_sym(symbol)
        try:
            df = yf.Ticker(ysym).history(period=period, interval=interval,
                                          auto_adjust=True, raise_errors=False)
            if df is None or df.empty:
                return []
            result = []
            for ts, row in df.iterrows():
                dt = ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else ts
                result.append(CandleBar(dt, row["Open"], row["High"], row["Low"],
                                        row["Close"], row.get("Volume", 0)))
            return result
        except Exception as e:
            logger.debug("yfinance history %s: %s", symbol, e)
            return []

    # ... (Stooq and AV methods omitted for brevity)

    # ── Live quotes ───────────────────────────────────────────────────────────

    def get_live_quote(self, symbol: str) -> dict:
        """Single quote with 30-second cache."""
        with self._lock:
            if symbol in self._quote_cache and time.time() < self._quote_ttl.get(symbol, 0):
                return self._quote_cache[symbol]

        q = {}
        if NSE_PYTHON_AVAILABLE:
            q = self._nse_quote(symbol)
        if not q and OA_AVAILABLE:
            q = self._oa_quote(symbol)
        if not q and YF_AVAILABLE:
            q = self._yf_quote(symbol)
        if not q and REQUESTS_AVAILABLE:
            q = self._stooq_quote(symbol)

        if q:
            with self._lock:
                self._quote_cache[symbol] = q
                self._quote_ttl[symbol]   = time.time() + 30
        return q

    def _nse_quote(self, symbol: str) -> dict:
        """Fetch live quote from nsepython."""
        try:
            q = nse_quote(symbol)
            if q:
                pinfo = q.get('priceInfo', {})
                return {
                    "symbol": symbol,
                    "ltp":    round(float(pinfo.get('lastPrice', 0)), 2),
                    "open":   round(float(pinfo.get('open', 0)), 2),
                    "high":   round(float(pinfo.get('high', 0)), 2),
                    "low":    round(float(pinfo.get('low', 0)), 2),
                    "volume": int(q.get('totalTradedVolume', 0)),
                    "timestamp": datetime.now().isoformat(),
                    "source": "nsepython",
                }
        except Exception as e:
            logger.debug("nsepython quote %s: %s", symbol, e)
        return {}

    def _yf_quote(self, symbol: str) -> dict:
        ysym = _yahoo_sym(symbol)
        try:
            info = yf.Ticker(ysym).fast_info
            return {
                "symbol": symbol,
                "ltp":    round(float(info.last_price or 0), 2),
                "open":   round(float(info.open or 0), 2),
                "high":   round(float(info.day_high or 0), 2),
                "low":    round(float(info.day_low or 0), 2),
                "volume": int(info.three_month_average_volume or 0),
                "timestamp": datetime.now().isoformat(),
                "source": "yfinance",
            }
        except Exception as e:
            logger.debug("yf quote %s: %s", symbol, e)
            return {}

    def _stooq_quote(self, symbol: str) -> dict:
        """
        Stooq real-time-ish quote via CSV (delayed ~15min).
        URL: https://stooq.com/q/l/?s=SYMBOL.ns&f=sd2t2ohlcv&h&e=csv
        """
        stooq_sym = _yahoo_sym(symbol).lower()
        url = f"https://stooq.com/q/l/?s={stooq_sym}&f=sd2t2ohlcv&h&e=csv"
        try:
            resp = req.get(url, timeout=8, headers={"User-Agent": "Mozilla/5.0"})
            if resp.status_code != 200:
                return {}
            df = pd.read_csv(io.StringIO(resp.text))
            if df.empty:
                return {}
            row = df.iloc[-1]
            close = float(row.get("Close", 0) or 0)
            if close == 0:
                return {}
            return {
                "symbol":    symbol,
                "ltp":       round(close, 2),
                "open":      round(float(row.get("Open", close) or close), 2),
                "high":      round(float(row.get("High", close) or close), 2),
                "low":       round(float(row.get("Low", close)  or close), 2),
                "volume":    int(row.get("Volume", 0) or 0),
                "timestamp": datetime.now().isoformat(),
                "source":    "stooq",
            }
        except Exception as e:
            logger.debug("Stooq quote %s: %s", symbol, e)
            return {}

    def _oa_quote(self, symbol: str) -> dict:
        try:
            resp = req.get(f"{OPENALGO_HOST}/quote",
                           params={"symbol": symbol, "exchange": "NSE"},
                           headers={"X-API-KEY": OPENALGO_KEY}, timeout=3)
            resp.raise_for_status()
            d = resp.json().get("data", {})
            d["source"] = "openalgo"
            return d
        except Exception:
            return {}

    # ── Batch quotes ──────────────────────────────────────────────────────────

    def fetch_all_quotes(self, symbols: list[str]) -> dict[str, dict]:
        """Batch fetch. Falls back to serial fetching if batch fails."""
        if YF_AVAILABLE:
            result = self._yf_batch_quotes(symbols)
            if result:
                with self._lock:
                    self._quote_cache.update(result)
                    exp = time.time() + 30
                    for s in result:
                        self._quote_ttl[s] = exp
                return result
        # Serial fallback
        result = {}
        for sym in symbols:
            q = self.get_live_quote(sym)
            if q:
                result[sym] = q
        return result

    def _yf_batch_quotes(self, symbols: list[str]) -> dict[str, dict]:
        """Fixed batch download — handles yfinance MultiIndex correctly."""
        yahoo_syms  = [_yahoo_sym(s) for s in symbols]
        reverse_map = {_yahoo_sym(s): s for s in symbols}
        try:
            raw = yf.download(
                tickers=yahoo_syms,
                period="1d", interval="1m",
                auto_adjust=True, progress=False, threads=True,
                group_by="ticker",
            )
            if raw is None or raw.empty:
                return {}

            result = {}
            is_multi = isinstance(raw.columns, pd.MultiIndex)

            for ysym in yahoo_syms:
                nse = reverse_map.get(ysym, ysym)
                try:
                    if is_multi:
                        # MultiIndex: (field, ticker)
                        sub = raw.xs(ysym, axis=1, level=1) if ysym in raw.columns.get_level_values(1) else None
                        if sub is None or sub.empty:
                            continue
                    else:
                        sub = raw  # single ticker fallback

                    close  = sub["Close"].dropna()
                    if close.empty:
                        continue
                    high_s = sub.get("High", close)
                    low_s  = sub.get("Low",  close)
                    result[nse] = {
                        "symbol":    nse,
                        "ltp":       round(float(close.iloc[-1]), 2),
                        "open":      round(float(close.iloc[0]),  2),
                        "high":      round(float(high_s.max()),   2),
                        "low":       round(float(low_s.min()),    2),
                        "volume":    0,
                        "timestamp": datetime.now().isoformat(),
                        "source":    "yfinance_batch",
                    }
                except Exception:
                    pass
            return result
        except Exception as e:
            logger.error("yf batch error: %s", e)
            return {}

    # ── Indices ───────────────────────────────────────────────────────────────

    def get_nifty_vix(self) -> tuple[float, float, float]:
        """Returns (nifty50, banknifty, vix)."""
        if NSE_PYTHON_AVAILABLE:
            try:
                nifty = nse_quote_ltp("NIFTY 50")
                bnk   = nse_quote_ltp("NIFTY BANK")
                vix   = nse_quote_ltp("INDIA VIX")
                return round(float(nifty), 2), round(float(bnk), 2), round(float(vix), 2)
            except Exception as e:
                logger.error("nsepython Index/VIX error: %s", e)

        if YF_AVAILABLE:
            try:
                raw = yf.download("^NSEI ^NSEBANK ^INDIAVIX",
                                  period="1d", interval="1m", progress=False)
                def _last(sym):
                    try:
                        col = ("Close", sym) if isinstance(raw.columns, pd.MultiIndex) else "Close"
                        return round(float(raw[col].dropna().iloc[-1]), 2)
                    except Exception:
                        return 0.0
                return _last("^NSEI"), _last("^NSEBANK"), _last("^INDIAVIX")
            except Exception as e:
                logger.error("Index/VIX error: %s", e)

        return 0.0, 0.0, 0.0

    # ── NSE bhav copy (EOD free source) ──────────────────────────────────────

    def get_nse_bhav(self, symbol: str) -> dict:
        """
        NSE bhav copy — free EOD data from NSE India.
        Returns today's or last trading day's OHLCV.
        """
        if not REQUESTS_AVAILABLE:
            return {}
        now  = datetime.now(IST)
        date = now.strftime("%d%b%Y").upper()
        url  = f"https://archives.nseindia.com/content/historical/EQUITIES/{now.year}/{now.strftime('%b').upper()}/cm{date}bhav.csv.zip"
        try:
            import zipfile
            resp = req.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
            if not resp.ok:
                return {}
            with zipfile.ZipFile(io.BytesIO(resp.content)) as z:
                fname = z.namelist()[0]
                df = pd.read_csv(z.open(fname))
            df.columns = [c.strip() for c in df.columns]
            row = df[df["SYMBOL"].str.strip() == symbol.upper()]
            if row.empty:
                return {}
            r = row.iloc[0]
            return {
                "symbol":  symbol,
                "open":    float(r.get("OPEN", 0)),
                "high":    float(r.get("HIGH", 0)),
                "low":     float(r.get("LOW",  0)),
                "close":   float(r.get("CLOSE", 0)),
                "ltp":     float(r.get("CLOSE", 0)),
                "volume":  int(r.get("TOTTRDQTY", 0)),
                "source":  "nse_bhav",
                "timestamp": datetime.now().isoformat(),
            }
        except Exception as e:
            logger.debug("NSE bhav error %s: %s", symbol, e)
            return {}

    # ── Background polling ────────────────────────────────────────────────────

    def start_polling(self, symbols: list[str], interval_sec: int = 15):
        self._running = True
        def _poll():
            while self._running:
                try:
                    self.fetch_all_quotes(symbols)
                    for cb in self._subscribers:
                        try:
                            cb(self._quote_cache.copy())
                        except Exception as e:
                            logger.error("Subscriber error: %s", e)
                except Exception as e:
                    logger.error("Poll error: %s", e)
                time.sleep(interval_sec)
        self._poll_thread = threading.Thread(target=_poll, daemon=True, name="MarketPoller")
        self._poll_thread.start()
        logger.info("Polling started every %ds", interval_sec)

    def stop_polling(self):
        self._running = False
        if self._poll_thread:
            self._poll_thread.join(timeout=5)

    def on_quote_update(self, callback):
        self._subscribers.append(callback)

    def get_cached(self, symbol: str) -> list[CandleBar]:
        with self._lock:
            return self._hist_cache.get(f"{symbol}:3mo:15m", [])

    def all_quotes(self) -> dict[str, dict]:
        with self._lock:
            return self._quote_cache.copy()


# ── Market hours ──────────────────────────────────────────────────────────────

def is_market_open() -> bool:
    """True during NSE trading hours: Mon–Fri 09:15–15:30 IST."""
    now = datetime.now(IST)
    if now.weekday() >= 5:
        return False
    o = now.replace(hour=9,  minute=15, second=0, microsecond=0)
    c = now.replace(hour=15, minute=30, second=0, microsecond=0)
    return o <= now <= c


def next_market_open() -> datetime:
    now  = datetime.now(IST)
    cand = now.replace(hour=9, minute=15, second=0, microsecond=0)
    if now >= cand:
        cand += timedelta(days=1)
    while cand.weekday() >= 5:
        cand += timedelta(days=1)
    return cand
