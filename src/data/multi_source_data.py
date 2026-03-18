"""
src/data/multi_source_data.py  —  AlphaZero Capital
═══════════════════════════════════════════════════════
Unified Multi-Source Market Data Engine  (v3.0)

Data Source Priority — Live Quotes:
  1. Upstox Native API   — best real-time (if UPSTOX_ACCESS_TOKEN set)
  2. OpenAlgo / Broker   — broker-grade real-time (if OPENALGO_KEY set)
  3. yfinance            — Yahoo Finance fast_info (free, ~15min delay)
  4. NSE Direct          — nseindia.com bhav copy / NseIndia API (free EOD)
  5. Stooq               — stooq.com CSV (free, EOD/delayed)
  6. Twelve Data         — if TWELVE_DATA_KEY set (60 req/min on free)
  7. Finnhub             — if FINNHUB_KEY set (60 req/min on free)
  8. Alpha Vantage       — if ALPHA_VANTAGE_KEY set (5 req/min free)

Data Source Priority — Historical Candles:
  1. Upstox Native API   — best (if UPSTOX_ACCESS_TOKEN set)
  2. OpenAlgo            — if OPENALGO_KEY set
  3. yfinance            — best free intraday (60-day limit)
  4. Twelve Data         — if TWELVE_DATA_KEY set (good intraday history)
  5. Stooq              — daily candles, unlimited history (no intraday)
  6. NSE Direct          — EOD bhav copy
  7. Alpha Vantage       — if ALPHA_VANTAGE_KEY set (limited free tier)
  8. Finnhub             — if FINNHUB_KEY set

News / Sentiment Sources:
  1. Finnhub Company News  — if FINNHUB_KEY set
  2. Twelve Data News      — if TWELVE_DATA_KEY set
  3. NSE Announcements     — nseindia.com/api/corporate-announcements

Set env vars in .env:
  UPSTOX_API_KEY        = your-key
  UPSTOX_API_SECRET     = your-secret
  UPSTOX_ACCESS_TOKEN   = your-daily-access-token   (auto-refreshed if possible)
  OPENALGO_HOST         = http://localhost:5000
  OPENALGO_KEY          = your-key
  ALPHA_VANTAGE_KEY     = your-key
  TWELVE_DATA_KEY       = your-key
  FINNHUB_KEY           = your-key
"""

from __future__ import annotations
import os
import io
import json
import time
import logging
import threading
from datetime import datetime, timedelta, date
from typing import Optional, List, Dict, Any, Tuple
from zoneinfo import ZoneInfo
from dataclasses import dataclass, asdict

import pandas as pd
import numpy as np

logger = logging.getLogger("MultiSourceData")
IST   = ZoneInfo("Asia/Kolkata")

# ── Optional Dependency Flags ─────────────────────────────────────────────────
try:
    import requests as _req
    REQUESTS_OK = True
except ImportError:
    REQUESTS_OK = False
    logger.warning("requests not installed — pip install requests")

try:
    import yfinance as yf
    YF_OK = True
except ImportError:
    YF_OK = False

try:
    import nsepython  # noqa: F401
    NSE_PY_OK = True
except ImportError:
    NSE_PY_OK = False

# ── API Keys from env ─────────────────────────────────────────────────────────
_AV_KEY          = os.getenv("ALPHA_VANTAGE_KEY", "")
_TD_KEY          = os.getenv("TWELVE_DATA_KEY", "")
_FH_KEY          = os.getenv("FINNHUB_KEY", "")
_OA_HOST         = os.getenv("OPENALGO_HOST", os.getenv("OPENALGO_URL", "http://127.0.0.1:5000"))
_OA_KEY          = os.getenv("OPENALGO_KEY", os.getenv("OPENALGO_API_KEY", ""))
_UPSTOX_KEY      = os.getenv("UPSTOX_API_KEY", "")
_UPSTOX_SECRET   = os.getenv("UPSTOX_API_SECRET", "")
_UPSTOX_TOKEN    = os.getenv("UPSTOX_ACCESS_TOKEN", "")   # daily refresh token

AV_OK      = bool(_AV_KEY)
TD_OK      = bool(_TD_KEY)
FH_OK      = bool(_FH_KEY)
OA_OK      = bool(_OA_KEY)
UPSTOX_OK  = bool(_UPSTOX_TOKEN or (_UPSTOX_KEY and _UPSTOX_SECRET))

# ── Upstox instrument ISIN / token map (pre-loaded) ──────────────────────────
# Upstox requires an instrument_key like NSE_EQ|INE002A01018 for RELIANCE
# We keep a mini-map of top 50 NIFTY stocks; full map can be loaded from
# https://assets.upstox.com/market-quote/instruments/exchange/NSE.json.gz
_UPSTOX_ISIN: Dict[str, str] = {
    "RELIANCE":   "NSE_EQ|INE002A01018",
    "TCS":        "NSE_EQ|INE467B01029",
    "HDFCBANK":   "NSE_EQ|INE040A01034",
    "INFY":       "NSE_EQ|INE009A01021",
    "ICICIBANK":  "NSE_EQ|INE090A01021",
    "KOTAKBANK":  "NSE_EQ|INE237A01028",
    "SBIN":       "NSE_EQ|INE062A01020",
    "HINDUNILVR": "NSE_EQ|INE030A01027",
    "BHARTIARTL": "NSE_EQ|INE397D01024",
    "ITC":        "NSE_EQ|INE154A01025",
    "WIPRO":      "NSE_EQ|INE075A01022",
    "HCLTECH":    "NSE_EQ|INE860A01027",
    "AXISBANK":   "NSE_EQ|INE238A01034",
    "LT":         "NSE_EQ|INE018A01030",
    "MARUTI":     "NSE_EQ|INE585B01010",
    "BAJFINANCE": "NSE_EQ|INE296A01024",
    "TATAMOTORS": "NSE_EQ|INE155A01022",
    "TATASTEEL":  "NSE_EQ|INE081A01020",
    "SUNPHARMA":  "NSE_EQ|INE044A01036",
    "NTPC":       "NSE_EQ|INE733E01010",
    "POWERGRID":  "NSE_EQ|INE752E01010",
    "TECHM":      "NSE_EQ|INE669C01036",
    "ULTRACEMCO": "NSE_EQ|INE481G01011",
    "ASIANPAINT": "NSE_EQ|INE021A01026",
    "HINDALCO":   "NSE_EQ|INE038A01020",
    "JSWSTEEL":   "NSE_EQ|INE019A01038",
    "ONGC":       "NSE_EQ|INE213A01029",
    "COALINDIA":  "NSE_EQ|INE522F01014",
    "DRREDDY":    "NSE_EQ|INE088D01014",
    "CIPLA":      "NSE_EQ|INE059A01026",
    "ADANIPORTS": "NSE_EQ|INE742F01042",
    "NESTLEIND":  "NSE_EQ|INE239A01016",
    "BRITANNIA":  "NSE_EQ|INE216A01030",
}

# NSE → Yahoo Finance suffix map
_YF_MAP: Dict[str, str] = {}  # auto-generated below


def _to_yf(sym: str) -> str:
    if sym in _YF_MAP:
        return _YF_MAP[sym]
    if sym.endswith(".NS") or sym.startswith("^"):
        return sym
    return sym + ".NS"


# Finnhub uses LSE/NYSE tickers; for NSE we add .NS (Finnhub supports NSE via exchange=NSE)
def _to_fh(sym: str) -> str:
    return sym   # Finnhub accepts plain NSE symbols when exchange=NSE is specified


@dataclass
class CandleBar:
    timestamp: datetime
    open:   float
    high:   float
    low:    float
    close:  float
    volume: int

    def to_dict(self) -> Dict:
        return {
            "timestamp": self.timestamp.isoformat(),
            "open":  self.open,
            "high":  self.high,
            "low":   self.low,
            "close": self.close,
            "volume": self.volume,
        }


@dataclass
class NewsItem:
    headline:   str
    summary:    str
    source:     str
    url:        str
    published:  datetime
    sentiment:  str   = "NEUTRAL"   # BULLISH | BEARISH | NEUTRAL
    score:      float = 0.0


class RateLimiter:
    """Simple token-bucket rate limiter per source."""
    def __init__(self, calls_per_min: int):
        self._max  = calls_per_min
        self._tokens = float(calls_per_min)
        self._last   = time.monotonic()
        self._lock   = threading.Lock()

    def acquire(self, timeout: float = 10.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self._lock:
                now = time.monotonic()
                elapsed = now - self._last
                self._tokens = min(self._max, self._tokens + elapsed * (self._max / 60))
                self._last = now
                if self._tokens >= 1:
                    self._tokens -= 1
                    return True
            time.sleep(0.5)
        return False


# Per-source rate limiters (free tier defaults)
_RL: Dict[str, RateLimiter] = {
    "alphavantage": RateLimiter(5),
    "twelvedata":   RateLimiter(55),
    "finnhub":      RateLimiter(55),
    "stooq":        RateLimiter(30),
    "yfinance":     RateLimiter(60),
    "nsedirect":    RateLimiter(10),
    "upstox":       RateLimiter(100),
    "openalgo":     RateLimiter(200),
}


# ═════════════════════════════════════════════════════════════════════════════
# MULTI-SOURCE ENGINE
# ═════════════════════════════════════════════════════════════════════════════

class MultiSourceData:
    """
    Unified multi-source data engine for AlphaZero Capital.

    Usage:
        msd = MultiSourceData()
        quote = msd.get_quote("RELIANCE")
        candles = msd.get_candles("RELIANCE", period="60d", interval="15m")
        news = msd.get_news("RELIANCE", days=3)
    """

    CACHE_TTL_QUOTE    = 15   # seconds — live quote
    CACHE_TTL_CANDLES  = 300  # seconds — candle bars
    CACHE_TTL_NEWS     = 600  # seconds — news items

    def __init__(self):
        self._lock  = threading.Lock()
        self._qcache: Dict[str, Tuple[float, Dict]]       = {}
        self._ccache: Dict[str, Tuple[float, List[CandleBar]]] = {}
        self._ncache: Dict[str, Tuple[float, List[NewsItem]]] = {}

        self._upstox_token: str = _UPSTOX_TOKEN
        logger.info(
            "MultiSourceData init — sources: "
            f"Upstox={'✓' if UPSTOX_OK else '✗'} "
            f"OpenAlgo={'✓' if OA_OK else '✗'} "
            f"yfinance={'✓' if YF_OK else '✗'} "
            f"TwelveData={'✓' if TD_OK else '✗'} "
            f"Finnhub={'✓' if FH_OK else '✗'} "
            f"AlphaVantage={'✓' if AV_OK else '✗'} "
            f"NSEDirect={'✓' if NSE_PY_OK or REQUESTS_OK else '✗'}"
        )

    # ── Public: Quote ─────────────────────────────────────────────────────────

    def get_quote(self, symbol: str) -> Dict[str, Any]:
        """
        Fetch latest quote for NSE symbol.

        Returns dict with keys:
          ltp, open, high, low, close, volume, change, change_pct,
          bid, ask, source (which data source answered)
        """
        with self._lock:
            cached = self._qcache.get(symbol)
            if cached and time.time() - cached[0] < self.CACHE_TTL_QUOTE:
                return cached[1]

        q = (
            self._upstox_quote(symbol)
            or self._openalgo_quote(symbol)
            or self._yf_quote(symbol)
            or self._nsedirect_quote(symbol)
            or self._stooq_quote(symbol)
            or self._td_quote(symbol)
            or self._fh_quote(symbol)
            or self._av_quote(symbol)
        )
        if q:
            with self._lock:
                self._qcache[symbol] = (time.time(), q)
        return q or {}

    # ── Public: Candles ───────────────────────────────────────────────────────

    def get_candles(
        self,
        symbol: str,
        period: str  = "60d",
        interval: str = "1d"
    ) -> List[CandleBar]:
        """
        Fetch OHLCV bars.

        period   : "1d" "7d" "30d" "60d" "1y" "2y" "5y"
        interval : "1m" "5m" "15m" "30m" "1h" "1d" "1wk"

        Returns list of CandleBar sorted oldest-first.
        """
        key = f"{symbol}_{period}_{interval}"
        with self._lock:
            cached = self._ccache.get(key)
            if cached and time.time() - cached[0] < self.CACHE_TTL_CANDLES:
                return cached[1]

        candles = (
            self._upstox_candles(symbol, period, interval)
            or self._openalgo_candles(symbol, period, interval)
            or self._yf_candles(symbol, period, interval)
            or self._td_candles(symbol, period, interval)
            or self._stooq_candles(symbol, period)       # stooq = daily only
            or self._nsedirect_candles(symbol, period)   # EOD
            or self._av_candles(symbol, interval)
            or self._fh_candles(symbol, period)
        )
        if candles:
            with self._lock:
                self._ccache[key] = (time.time(), candles)
        return candles or []

    # ── Public: News ──────────────────────────────────────────────────────────

    def get_news(self, symbol: str, days: int = 3) -> List[NewsItem]:
        """
        Fetch recent company news / announcements.

        Returns list of NewsItem sorted newest-first.
        """
        with self._lock:
            cached = self._ncache.get(symbol)
            if cached and time.time() - cached[0] < self.CACHE_TTL_NEWS:
                return cached[1]

        news = (
            self._fh_news(symbol, days)
            or self._td_news(symbol, days)
            or self._nsedirect_news(symbol, days)
        )
        if news:
            with self._lock:
                self._ncache[symbol] = (time.time(), news)
        return news or []

    # ── Public: Bulk Quotes ───────────────────────────────────────────────────

    def get_bulk_quotes(self, symbols: List[str]) -> Dict[str, Dict]:
        """Fetch quotes for multiple symbols efficiently."""
        result: Dict[str, Dict] = {}

        # Try Upstox bulk endpoint first
        if UPSTOX_OK and REQUESTS_OK and self._upstox_token:
            result = self._upstox_bulk_quote(symbols)

        # Fill missing via OpenAlgo or individual calls
        missing = [s for s in symbols if s not in result]
        if missing and OA_OK:
            for sym in missing:
                q = self._openalgo_quote(sym)
                if q:
                    result[sym] = q

        # Fallback: yfinance bulk download
        still_missing = [s for s in symbols if s not in result]
        if still_missing and YF_OK:
            yf_result = self._yf_bulk_quote(still_missing)
            result.update(yf_result)

        return result

    # ══════════════════════════════════════════════════════════════════════════
    # SOURCE 1 — UPSTOX NATIVE API
    # ══════════════════════════════════════════════════════════════════════════

    def _upstox_quote(self, symbol: str) -> Optional[Dict]:
        if not UPSTOX_OK or not REQUESTS_OK or not self._upstox_token:
            return None
        ikey = _UPSTOX_ISIN.get(symbol, f"NSE_EQ|{symbol}")
        if not _RL["upstox"].acquire(timeout=2):
            return None
        try:
            url = "https://api.upstox.com/v2/market-quote/quotes"
            headers = {
                "Authorization": f"Bearer {self._upstox_token}",
                "Accept": "application/json",
            }
            r = _req.get(url, headers=headers, params={"symbol": ikey}, timeout=5)
            r.raise_for_status()
            data = r.json().get("data", {})
            if not data:
                return None
            key = list(data.keys())[0]
            d   = data[key]
            ohlc = d.get("ohlc", {})
            return {
                "ltp":        d.get("last_price", 0),
                "open":       ohlc.get("open", 0),
                "high":       ohlc.get("high", 0),
                "low":        ohlc.get("low", 0),
                "close":      ohlc.get("close", 0),
                "volume":     d.get("volume", 0),
                "change":     d.get("net_change", 0),
                "change_pct": d.get("net_change", 0) / max(ohlc.get("close", 1), 1) * 100,
                "bid":        d.get("depth", {}).get("buy", [{}])[0].get("price", 0),
                "ask":        d.get("depth", {}).get("sell", [{}])[0].get("price", 0),
                "source":     "UPSTOX",
            }
        except Exception as e:
            logger.debug("[Upstox] quote error for %s: %s", symbol, e)
            return None

    def _upstox_bulk_quote(self, symbols: List[str]) -> Dict[str, Dict]:
        """Upstox supports comma-separated instrument keys."""
        if not UPSTOX_OK or not REQUESTS_OK or not self._upstox_token:
            return {}
        ikeys = ",".join(_UPSTOX_ISIN.get(s, f"NSE_EQ|{s}") for s in symbols)
        try:
            url = "https://api.upstox.com/v2/market-quote/quotes"
            headers = {"Authorization": f"Bearer {self._upstox_token}", "Accept": "application/json"}
            r = _req.get(url, headers=headers, params={"symbol": ikeys}, timeout=10)
            r.raise_for_status()
            raw = r.json().get("data", {})
            result = {}
            for sym in symbols:
                ikey = _UPSTOX_ISIN.get(sym, f"NSE_EQ|{sym}")
                d = raw.get(ikey, {})
                if d:
                    ohlc = d.get("ohlc", {})
                    result[sym] = {
                        "ltp":        d.get("last_price", 0),
                        "open":       ohlc.get("open", 0),
                        "high":       ohlc.get("high", 0),
                        "low":        ohlc.get("low", 0),
                        "close":      ohlc.get("close", 0),
                        "volume":     d.get("volume", 0),
                        "change":     d.get("net_change", 0),
                        "change_pct": d.get("net_change", 0) / max(ohlc.get("close", 1), 1) * 100,
                        "source":     "UPSTOX",
                    }
            return result
        except Exception as e:
            logger.debug("[Upstox] bulk quote error: %s", e)
            return {}

    def _upstox_candles(self, symbol: str, period: str, interval: str) -> Optional[List[CandleBar]]:
        """Upstox historical candles API."""
        if not UPSTOX_OK or not REQUESTS_OK or not self._upstox_token:
            return None
        ikey = _UPSTOX_ISIN.get(symbol, f"NSE_EQ|{symbol}")
        # Map interval
        interval_map = {
            "1m":  "1minute", "5m": "5minute", "15m": "15minute",
            "30m": "30minute", "1h": "60minute", "1d": "day", "1wk": "week",
        }
        up_interval = interval_map.get(interval, "day")
        unit = "days" if up_interval == "day" else "minutes"
        to_dt   = datetime.now(IST)
        period_days = self._period_to_days(period)
        from_dt = to_dt - timedelta(days=period_days)
        if not _RL["upstox"].acquire(timeout=2):
            return None
        try:
            url = f"https://api.upstox.com/v2/historical-candle/{ikey}/{up_interval}/{to_dt.strftime('%Y-%m-%d')}/{from_dt.strftime('%Y-%m-%d')}"
            headers = {"Authorization": f"Bearer {self._upstox_token}", "Accept": "application/json"}
            r = _req.get(url, headers=headers, timeout=10)
            r.raise_for_status()
            candles_raw = r.json().get("data", {}).get("candles", [])
            bars = []
            for c in candles_raw:
                # [timestamp, open, high, low, close, volume, oi]
                try:
                    ts = datetime.fromisoformat(c[0]).replace(tzinfo=IST)
                    bars.append(CandleBar(ts, float(c[1]), float(c[2]), float(c[3]), float(c[4]), int(c[5])))
                except Exception:
                    pass
            return sorted(bars, key=lambda x: x.timestamp) if bars else None
        except Exception as e:
            logger.debug("[Upstox] candles error for %s: %s", symbol, e)
            return None

    # ══════════════════════════════════════════════════════════════════════════
    # SOURCE 2 — OPENALGO (Broker Bridge)
    # ══════════════════════════════════════════════════════════════════════════

    def _openalgo_quote(self, symbol: str) -> Optional[Dict]:
        if not OA_OK or not REQUESTS_OK:
            return None
        try:
            url = f"{_OA_HOST}/api/v1/quotes"
            r = _req.post(url, json={"apikey": _OA_KEY, "symbol": symbol, "exchange": "NSE"}, timeout=5)
            r.raise_for_status()
            d = r.json()
            if d.get("status") == "success":
                q = d.get("data", {})
                return {
                    "ltp":        q.get("ltp", q.get("close", 0)),
                    "open":       q.get("open", 0),
                    "high":       q.get("high", 0),
                    "low":        q.get("low", 0),
                    "close":      q.get("close", 0),
                    "volume":     q.get("volume", 0),
                    "change":     q.get("change", 0),
                    "change_pct": q.get("pct_change", 0),
                    "source":     "OPENALGO",
                }
        except Exception as e:
            logger.debug("[OpenAlgo] quote error for %s: %s", symbol, e)
        return None

    def _openalgo_candles(self, symbol: str, period: str, interval: str) -> Optional[List[CandleBar]]:
        if not OA_OK or not REQUESTS_OK:
            return None
        interval_map = {"1m": "1", "5m": "5", "15m": "15", "30m": "30", "1h": "60", "1d": "D"}
        payload = {
            "apikey":   _OA_KEY,
            "symbol":   symbol,
            "exchange": "NSE",
            "interval": interval_map.get(interval, "D"),
            "start_date": (datetime.now(IST) - timedelta(days=self._period_to_days(period))).strftime("%Y-%m-%d"),
            "end_date":   datetime.now(IST).strftime("%Y-%m-%d"),
        }
        try:
            r = _req.post(f"{_OA_HOST}/api/v1/history", json=payload, timeout=10)
            r.raise_for_status()
            d = r.json()
            if d.get("status") == "success":
                return self._parse_oa_candles(d.get("data", []))
        except Exception as e:
            logger.debug("[OpenAlgo] candles error for %s: %s", symbol, e)
        return None

    def _parse_oa_candles(self, raw: list) -> List[CandleBar]:
        bars = []
        for c in raw:
            try:
                ts = datetime.fromisoformat(str(c.get("time", c.get("timestamp", "")))).replace(tzinfo=IST)
                bars.append(CandleBar(ts, float(c["open"]), float(c["high"]), float(c["low"]), float(c["close"]), int(c.get("volume", 0))))
            except Exception:
                pass
        return sorted(bars, key=lambda x: x.timestamp)

    # ══════════════════════════════════════════════════════════════════════════
    # SOURCE 3 — YFINANCE
    # ══════════════════════════════════════════════════════════════════════════

    def _yf_quote(self, symbol: str) -> Optional[Dict]:
        if not YF_OK:
            return None
        if not _RL["yfinance"].acquire(timeout=3):
            return None
        try:
            tk = yf.Ticker(_to_yf(symbol))
            fi = tk.fast_info
            ltp = getattr(fi, "last_price", None) or getattr(fi, "regularMarketPrice", None)
            if not ltp:
                return None
            prev = getattr(fi, "previous_close", ltp)
            chg  = ltp - prev
            return {
                "ltp":        round(float(ltp), 2),
                "open":       round(float(getattr(fi, "open", ltp)), 2),
                "high":       round(float(getattr(fi, "day_high", ltp)), 2),
                "low":        round(float(getattr(fi, "day_low", ltp)), 2),
                "close":      round(float(prev), 2),
                "volume":     int(getattr(fi, "last_volume", 0)),
                "change":     round(float(chg), 2),
                "change_pct": round(float(chg / prev * 100) if prev else 0, 2),
                "source":     "YFINANCE",
            }
        except Exception as e:
            logger.debug("[yfinance] quote error for %s: %s", symbol, e)
        return None

    def _yf_bulk_quote(self, symbols: List[str]) -> Dict[str, Dict]:
        if not YF_OK:
            return {}
        try:
            yf_syms = [_to_yf(s) for s in symbols]
            tickers  = yf.Tickers(" ".join(yf_syms))
            result   = {}
            for sym, yfsym in zip(symbols, yf_syms):
                try:
                    tk  = tickers.tickers.get(yfsym)
                    if not tk:
                        continue
                    fi  = tk.fast_info
                    ltp = getattr(fi, "last_price", None)
                    if ltp:
                        prev = getattr(fi, "previous_close", ltp)
                        result[sym] = {
                            "ltp":        round(float(ltp), 2),
                            "open":       round(float(getattr(fi, "open", ltp)), 2),
                            "high":       round(float(getattr(fi, "day_high", ltp)), 2),
                            "low":        round(float(getattr(fi, "day_low", ltp)), 2),
                            "close":      round(float(prev), 2),
                            "volume":     int(getattr(fi, "last_volume", 0)),
                            "change_pct": round((ltp - prev) / prev * 100 if prev else 0, 2),
                            "source":     "YFINANCE",
                        }
                except Exception:
                    pass
            return result
        except Exception as e:
            logger.debug("[yfinance] bulk quote error: %s", e)
        return {}

    def _yf_candles(self, symbol: str, period: str, interval: str) -> Optional[List[CandleBar]]:
        if not YF_OK:
            return None
        # yfinance doesn't support 1m + long periods
        if interval == "1m" and self._period_to_days(period) > 7:
            period = "7d"
        if not _RL["yfinance"].acquire(timeout=3):
            return None
        try:
            tk  = yf.Ticker(_to_yf(symbol))
            yfi = {"1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m", "1h": "1h", "1d": "1d", "1wk": "1wk"}.get(interval, "1d")
            df  = tk.history(period=period, interval=yfi, auto_adjust=True)
            if df.empty:
                return None
            bars = []
            for ts, row in df.iterrows():
                try:
                    tz_ts = ts.to_pydatetime().replace(tzinfo=IST)
                    bars.append(CandleBar(tz_ts, float(row["Open"]), float(row["High"]), float(row["Low"]), float(row["Close"]), int(row["Volume"])))
                except Exception:
                    pass
            return bars or None
        except Exception as e:
            logger.debug("[yfinance] candles error for %s: %s", symbol, e)
        return None

    # ══════════════════════════════════════════════════════════════════════════
    # SOURCE 4 — NSE DIRECT  (nseindia.com public APIs)
    # ══════════════════════════════════════════════════════════════════════════

    def _nsedirect_quote(self, symbol: str) -> Optional[Dict]:
        """NSE India equity market data via public API."""
        if not REQUESTS_OK:
            return None
        if not _RL["nsedirect"].acquire(timeout=3):
            return None
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept":     "application/json",
                "Referer":    "https://www.nseindia.com",
            }
            session = _req.Session()
            session.get("https://www.nseindia.com", headers=headers, timeout=5)
            url = f"https://www.nseindia.com/api/quote-equity?symbol={symbol}"
            r   = session.get(url, headers=headers, timeout=8)
            r.raise_for_status()
            d   = r.json()
            pd_ = d.get("priceInfo", {})
            ltp = pd_.get("lastPrice", 0)
            if not ltp:
                return None
            return {
                "ltp":        float(ltp),
                "open":       float(pd_.get("open", ltp)),
                "high":       float(pd_.get("intraDayHighLow", {}).get("max", ltp)),
                "low":        float(pd_.get("intraDayHighLow", {}).get("min", ltp)),
                "close":      float(pd_.get("previousClose", ltp)),
                "volume":     int(d.get("marketDeptOrderBook", {}).get("totalTradedVolume", 0)),
                "change":     float(pd_.get("change", 0)),
                "change_pct": float(pd_.get("pChange", 0)),
                "source":     "NSE_DIRECT",
            }
        except Exception as e:
            logger.debug("[NSEDirect] quote error for %s: %s", symbol, e)
        return None

    def _nsedirect_candles(self, symbol: str, period: str) -> Optional[List[CandleBar]]:
        """NSE Bhav Copy (EOD) for historical data."""
        if not REQUESTS_OK:
            return None
        if not _RL["nsedirect"].acquire(timeout=3):
            return None
        try:
            headers = {
                "User-Agent": "Mozilla/5.0",
                "Accept":     "application/json",
                "Referer":    "https://www.nseindia.com",
            }
            session = _req.Session()
            session.get("https://www.nseindia.com", headers=headers, timeout=5)
            days   = self._period_to_days(period)
            end_dt = datetime.now(IST)
            start_dt = end_dt - timedelta(days=days)
            url = (
                f"https://www.nseindia.com/api/historical/cm/equity?"
                f"symbol={symbol}&series=[%22EQ%22]"
                f"&from={start_dt.strftime('%d-%m-%Y')}&to={end_dt.strftime('%d-%m-%Y')}"
            )
            r = session.get(url, headers=headers, timeout=10)
            r.raise_for_status()
            data = r.json().get("data", [])
            bars = []
            for c in data:
                try:
                    ts = datetime.strptime(c["CH_TIMESTAMP"], "%Y-%m-%d").replace(tzinfo=IST)
                    bars.append(CandleBar(ts, float(c["CH_OPENING_PRICE"]), float(c["CH_TRADE_HIGH_PRICE"]),
                                          float(c["CH_TRADE_LOW_PRICE"]), float(c["CH_CLOSING_PRICE"]),
                                          int(c.get("CH_TOT_TRADED_QTY", 0))))
                except Exception:
                    pass
            return sorted(bars, key=lambda x: x.timestamp) if bars else None
        except Exception as e:
            logger.debug("[NSEDirect] candles error for %s: %s", symbol, e)
        return None

    def _nsedirect_news(self, symbol: str, days: int) -> Optional[List[NewsItem]]:
        """NSE Corporate Announcements."""
        if not REQUESTS_OK:
            return None
        try:
            headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://www.nseindia.com"}
            session = _req.Session()
            session.get("https://www.nseindia.com", headers=headers, timeout=5)
            end_dt   = datetime.now(IST)
            start_dt = end_dt - timedelta(days=days)
            url = (
                f"https://www.nseindia.com/api/corporate-announcements"
                f"?index=equities&symbol={symbol}"
                f"&from_date={start_dt.strftime('%d-%m-%Y')}&to_date={end_dt.strftime('%d-%m-%Y')}"
            )
            r = session.get(url, headers=headers, timeout=10)
            r.raise_for_status()
            items_raw = r.json() if isinstance(r.json(), list) else r.json().get("data", [])
            items = []
            for ann in items_raw[:10]:
                try:
                    ts = datetime.strptime(ann.get("sort_date", ""), "%Y-%m-%d %H:%M:%S").replace(tzinfo=IST)
                    items.append(NewsItem(
                        headline  = ann.get("desc", ann.get("subject", "")),
                        summary   = ann.get("desc", ""),
                        source    = "NSE",
                        url       = ann.get("attchmntFile", ""),
                        published = ts,
                    ))
                except Exception:
                    pass
            return items or None
        except Exception as e:
            logger.debug("[NSEDirect] news error for %s: %s", symbol, e)
        return None

    # ══════════════════════════════════════════════════════════════════════════
    # SOURCE 5 — STOOQ
    # ══════════════════════════════════════════════════════════════════════════

    def _stooq_quote(self, symbol: str) -> Optional[Dict]:
        if not REQUESTS_OK:
            return None
        if not _RL["stooq"].acquire(timeout=3):
            return None
        try:
            stooq_sym = symbol.lower() + ".in"
            url = f"https://stooq.com/q/l/?s={stooq_sym}&f=sd2t2ohlcv&h&e=csv"
            r   = _req.get(url, timeout=8)
            r.raise_for_status()
            df  = pd.read_csv(io.StringIO(r.text))
            if df.empty or "Close" not in df.columns:
                return None
            row = df.iloc[-1]
            ltp = float(row["Close"])
            op  = float(row.get("Open", ltp))
            return {
                "ltp":        ltp,
                "open":       op,
                "high":       float(row.get("High", ltp)),
                "low":        float(row.get("Low", ltp)),
                "close":      ltp,
                "volume":     int(row.get("Volume", 0)),
                "change":     0.0,
                "change_pct": 0.0,
                "source":     "STOOQ",
            }
        except Exception as e:
            logger.debug("[Stooq] quote error for %s: %s", symbol, e)
        return None

    def _stooq_candles(self, symbol: str, period: str) -> Optional[List[CandleBar]]:
        """Stooq daily candles (no intraday)."""
        if not REQUESTS_OK:
            return None
        if not _RL["stooq"].acquire(timeout=3):
            return None
        try:
            stooq_sym = symbol.lower() + ".in"
            days = self._period_to_days(period)
            end_dt   = datetime.now(IST)
            start_dt = end_dt - timedelta(days=days)
            url = (
                f"https://stooq.com/q/d/l/?s={stooq_sym}&d1={start_dt.strftime('%Y%m%d')}"
                f"&d2={end_dt.strftime('%Y%m%d')}&i=d"
            )
            r = _req.get(url, timeout=10)
            r.raise_for_status()
            df = pd.read_csv(io.StringIO(r.text))
            if df.empty or "Close" not in df.columns:
                return None
            bars = []
            for _, row in df.iterrows():
                try:
                    ts = datetime.strptime(str(row["Date"]), "%Y-%m-%d").replace(tzinfo=IST)
                    bars.append(CandleBar(ts, float(row["Open"]), float(row["High"]),
                                          float(row["Low"]),  float(row["Close"]),
                                          int(row.get("Volume", 0))))
                except Exception:
                    pass
            return sorted(bars, key=lambda x: x.timestamp) if bars else None
        except Exception as e:
            logger.debug("[Stooq] candles error for %s: %s", symbol, e)
        return None

    # ══════════════════════════════════════════════════════════════════════════
    # SOURCE 6 — TWELVE DATA
    # ══════════════════════════════════════════════════════════════════════════

    def _td_quote(self, symbol: str) -> Optional[Dict]:
        if not TD_OK or not REQUESTS_OK:
            return None
        if not _RL["twelvedata"].acquire(timeout=3):
            return None
        try:
            url = "https://api.twelvedata.com/price"
            r   = _req.get(url, params={"symbol": f"{symbol}:NSE", "apikey": _TD_KEY}, timeout=8)
            r.raise_for_status()
            data = r.json()
            ltp  = float(data.get("price", 0))
            if not ltp:
                return None
            # Get OHLC via separate endpoint
            ohlc_r = _req.get("https://api.twelvedata.com/quote",
                               params={"symbol": f"{symbol}:NSE", "apikey": _TD_KEY}, timeout=8)
            ohlc_r.raise_for_status()
            ohlc = ohlc_r.json()
            return {
                "ltp":        ltp,
                "open":       float(ohlc.get("open", ltp)),
                "high":       float(ohlc.get("high", ltp)),
                "low":        float(ohlc.get("low", ltp)),
                "close":      float(ohlc.get("previous_close", ltp)),
                "volume":     int(ohlc.get("volume", 0)),
                "change":     float(ohlc.get("change", 0)),
                "change_pct": float(ohlc.get("percent_change", 0)),
                "source":     "TWELVE_DATA",
            }
        except Exception as e:
            logger.debug("[TwelveData] quote error for %s: %s", symbol, e)
        return None

    def _td_candles(self, symbol: str, period: str, interval: str) -> Optional[List[CandleBar]]:
        if not TD_OK or not REQUESTS_OK:
            return None
        if not _RL["twelvedata"].acquire(timeout=3):
            return None
        td_interval = {"1m": "1min", "5m": "5min", "15m": "15min", "30m": "30min",
                        "1h": "1h", "1d": "1day", "1wk": "1week"}.get(interval, "1day")
        days    = self._period_to_days(period)
        end_dt  = datetime.now(IST)
        start_dt = end_dt - timedelta(days=days)
        try:
            r = _req.get(
                "https://api.twelvedata.com/time_series",
                params={
                    "symbol":    f"{symbol}:NSE",
                    "interval":  td_interval,
                    "start_date": start_dt.strftime("%Y-%m-%d"),
                    "end_date":   end_dt.strftime("%Y-%m-%d"),
                    "outputsize": 5000,
                    "apikey":     _TD_KEY,
                },
                timeout=15,
            )
            r.raise_for_status()
            data   = r.json()
            values = data.get("values", [])
            if not values:
                return None
            bars = []
            for v in values:
                try:
                    ts = datetime.strptime(v["datetime"], "%Y-%m-%d %H:%M:%S" if " " in v["datetime"] else "%Y-%m-%d").replace(tzinfo=IST)
                    bars.append(CandleBar(ts, float(v["open"]), float(v["high"]),
                                          float(v["low"]),  float(v["close"]),
                                          int(v.get("volume", 0))))
                except Exception:
                    pass
            return sorted(bars, key=lambda x: x.timestamp) if bars else None
        except Exception as e:
            logger.debug("[TwelveData] candles error for %s: %s", symbol, e)
        return None

    def _td_news(self, symbol: str, days: int) -> Optional[List[NewsItem]]:
        """Twelve Data doesn't have a free news endpoint; skip gracefully."""
        return None

    # ══════════════════════════════════════════════════════════════════════════
    # SOURCE 7 — FINNHUB
    # ══════════════════════════════════════════════════════════════════════════

    def _fh_quote(self, symbol: str) -> Optional[Dict]:
        if not FH_OK or not REQUESTS_OK:
            return None
        if not _RL["finnhub"].acquire(timeout=3):
            return None
        try:
            r = _req.get(
                "https://finnhub.io/api/v1/quote",
                params={"symbol": f"NSE:{symbol}", "token": _FH_KEY},
                timeout=8,
            )
            r.raise_for_status()
            d = r.json()
            ltp = d.get("c", 0)
            if not ltp:
                return None
            return {
                "ltp":        float(ltp),
                "open":       float(d.get("o", ltp)),
                "high":       float(d.get("h", ltp)),
                "low":        float(d.get("l", ltp)),
                "close":      float(d.get("pc", ltp)),
                "volume":     0,
                "change":     float(d.get("d", 0)),
                "change_pct": float(d.get("dp", 0)),
                "source":     "FINNHUB",
            }
        except Exception as e:
            logger.debug("[Finnhub] quote error for %s: %s", symbol, e)
        return None

    def _fh_candles(self, symbol: str, period: str) -> Optional[List[CandleBar]]:
        """Finnhub candles (daily resolution on free tier)."""
        if not FH_OK or not REQUESTS_OK:
            return None
        if not _RL["finnhub"].acquire(timeout=3):
            return None
        days    = self._period_to_days(period)
        to_ts   = int(datetime.now(IST).timestamp())
        from_ts = int((datetime.now(IST) - timedelta(days=days)).timestamp())
        try:
            r = _req.get(
                "https://finnhub.io/api/v1/stock/candle",
                params={
                    "symbol":     f"NSE:{symbol}",
                    "resolution": "D",
                    "from":       from_ts,
                    "to":         to_ts,
                    "token":      _FH_KEY,
                },
                timeout=10,
            )
            r.raise_for_status()
            d = r.json()
            if d.get("s") != "ok":
                return None
            bars = []
            for i in range(len(d.get("t", []))):
                try:
                    ts = datetime.fromtimestamp(d["t"][i], tz=IST)
                    bars.append(CandleBar(ts, float(d["o"][i]), float(d["h"][i]),
                                          float(d["l"][i]), float(d["c"][i]),
                                          int(d.get("v", [0]*len(d["t"]))[i])))
                except Exception:
                    pass
            return sorted(bars, key=lambda x: x.timestamp) if bars else None
        except Exception as e:
            logger.debug("[Finnhub] candles error for %s: %s", symbol, e)
        return None

    def _fh_news(self, symbol: str, days: int) -> Optional[List[NewsItem]]:
        if not FH_OK or not REQUESTS_OK:
            return None
        if not _RL["finnhub"].acquire(timeout=3):
            return None
        try:
            end_dt   = datetime.now(IST)
            start_dt = end_dt - timedelta(days=days)
            r = _req.get(
                "https://finnhub.io/api/v1/company-news",
                params={
                    "symbol": f"NSE:{symbol}",
                    "from":   start_dt.strftime("%Y-%m-%d"),
                    "to":     end_dt.strftime("%Y-%m-%d"),
                    "token":  _FH_KEY,
                },
                timeout=10,
            )
            r.raise_for_status()
            raw   = r.json()
            items = []
            for n in raw[:15]:
                try:
                    ts = datetime.fromtimestamp(n.get("datetime", 0), tz=IST)
                    items.append(NewsItem(
                        headline  = n.get("headline", ""),
                        summary   = n.get("summary", ""),
                        source    = n.get("source", "Finnhub"),
                        url       = n.get("url", ""),
                        published = ts,
                    ))
                except Exception:
                    pass
            return items or None
        except Exception as e:
            logger.debug("[Finnhub] news error for %s: %s", symbol, e)
        return None

    # ══════════════════════════════════════════════════════════════════════════
    # SOURCE 8 — ALPHA VANTAGE
    # ══════════════════════════════════════════════════════════════════════════

    def _av_quote(self, symbol: str) -> Optional[Dict]:
        if not AV_OK or not REQUESTS_OK:
            return None
        if not _RL["alphavantage"].acquire(timeout=5):
            return None
        try:
            r = _req.get(
                "https://www.alphavantage.co/query",
                params={
                    "function": "GLOBAL_QUOTE",
                    "symbol":   f"NSE:{symbol}",
                    "apikey":   _AV_KEY,
                },
                timeout=10,
            )
            r.raise_for_status()
            q = r.json().get("Global Quote", {})
            ltp = float(q.get("05. price", 0))
            if not ltp:
                return None
            prev = float(q.get("08. previous close", ltp))
            return {
                "ltp":        ltp,
                "open":       float(q.get("02. open", ltp)),
                "high":       float(q.get("03. high", ltp)),
                "low":        float(q.get("04. low", ltp)),
                "close":      prev,
                "volume":     int(q.get("06. volume", 0)),
                "change":     float(q.get("09. change", 0)),
                "change_pct": float(q.get("10. change percent", "0").strip("%")),
                "source":     "ALPHA_VANTAGE",
            }
        except Exception as e:
            logger.debug("[AlphaVantage] quote error for %s: %s", symbol, e)
        return None

    def _av_candles(self, symbol: str, interval: str) -> Optional[List[CandleBar]]:
        if not AV_OK or not REQUESTS_OK:
            return None
        if not _RL["alphavantage"].acquire(timeout=10):
            return None
        func = {
            "1m": "TIME_SERIES_INTRADAY", "5m": "TIME_SERIES_INTRADAY",
            "15m": "TIME_SERIES_INTRADAY", "30m": "TIME_SERIES_INTRADAY",
            "1h": "TIME_SERIES_INTRADAY",
            "1d": "TIME_SERIES_DAILY", "1wk": "TIME_SERIES_WEEKLY",
        }.get(interval, "TIME_SERIES_DAILY")
        params = {"function": func, "symbol": f"NSE:{symbol}", "outputsize": "full", "apikey": _AV_KEY}
        if "INTRADAY" in func:
            av_int = {"1m": "1min", "5m": "5min", "15m": "15min", "30m": "30min", "1h": "60min"}.get(interval, "5min")
            params["interval"] = av_int
        try:
            r = _req.get("https://www.alphavantage.co/query", params=params, timeout=15)
            r.raise_for_status()
            data = r.json()
            key  = [k for k in data if "Time Series" in k]
            if not key:
                return None
            ts_data = data[key[0]]
            bars    = []
            for ts_str, ohlcv in ts_data.items():
                try:
                    ts = datetime.strptime(ts_str[:19], "%Y-%m-%d %H:%M:%S" if " " in ts_str else "%Y-%m-%d").replace(tzinfo=IST)
                    bars.append(CandleBar(
                        ts,
                        float(ohlcv.get("1. open", 0)),
                        float(ohlcv.get("2. high", 0)),
                        float(ohlcv.get("3. low", 0)),
                        float(ohlcv.get("4. close", 0)),
                        int(ohlcv.get("5. volume", 0)),
                    ))
                except Exception:
                    pass
            return sorted(bars, key=lambda x: x.timestamp) if bars else None
        except Exception as e:
            logger.debug("[AlphaVantage] candles error for %s: %s", symbol, e)
        return None

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _period_to_days(period: str) -> int:
        mapping = {
            "1d": 1, "2d": 2, "5d": 5, "7d": 7, "14d": 14, "1mo": 30, "30d": 30,
            "60d": 60, "2mo": 60, "3mo": 90, "6mo": 180, "1y": 365, "2y": 730,
            "5y": 1825, "max": 3650,
        }
        return mapping.get(period, 60)

    def get_source_status(self) -> Dict[str, bool]:
        """Return availability of each data source."""
        return {
            "upstox":       UPSTOX_OK,
            "openalgo":     OA_OK,
            "yfinance":     YF_OK,
            "nse_direct":   REQUESTS_OK,
            "stooq":        REQUESTS_OK,
            "twelve_data":  TD_OK,
            "finnhub":      FH_OK,
            "alpha_vantage": AV_OK,
        }

    def cache_info(self) -> Dict[str, Any]:
        """Summary of data engine for health checks."""
        return {
            "sources_active": sum(1 for v in self.get_source_status().values() if v),
            "source_status": self.get_source_status(),
            "timestamp": datetime.now(IST).isoformat(),
            "ok": True
        }

    def refresh_upstox_token(self, new_token: str):
        """Update Upstox access token (call after daily OAuth refresh)."""
        self._upstox_token = new_token
        logger.info("[Upstox] Access token refreshed.")


# ── Module-level singleton ────────────────────────────────────────────────────
_MSD_INSTANCE: Optional[MultiSourceData] = None
_MSD_LOCK = threading.Lock()

def get_msd() -> MultiSourceData:
    global _MSD_INSTANCE
    with _MSD_LOCK:
        if _MSD_INSTANCE is None:
            _MSD_INSTANCE = MultiSourceData()
    return _MSD_INSTANCE


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    msd = MultiSourceData()
    print("Source status:", msd.get_source_status())
    print("\nTesting RELIANCE quote:")
    q = msd.get_quote("RELIANCE")
    print(q)
    print("\nTesting RELIANCE daily candles (30d):")
    candles = msd.get_candles("RELIANCE", period="30d", interval="1d")
    print(f"Got {len(candles)} bars. Last: {candles[-1] if candles else 'None'}")
    print("\nTesting RELIANCE news:")
    news = msd.get_news("RELIANCE", days=2)
    print(f"Got {len(news)} news items.")
    for n in news[:2]:
        print(f"  [{n.source}] {n.headline[:60]}")
