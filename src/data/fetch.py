"""
DataFetcher - Market Data Abstraction Layer
src/data/fetch.py

FIXED: Replaced all random/simulated data with real NSE data via yfinance.
       _fetch_live() and _fetch_ohlcv_live() now work correctly.
       PAPER mode also uses real data (no random numbers anywhere).
       OpenAlgo is used as primary source in LIVE mode; yfinance is fallback.

Public API is 100% identical to the original — no other files need changing.
"""

import logging
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any

import pandas as pd
import numpy as np

# yfinance for real NSE data
try:
    import yfinance as yf
    YFINANCE_OK = True
except ImportError:
    YFINANCE_OK = False

# requests for OpenAlgo live mode
try:
    import requests as _requests
    REQUESTS_OK = True
except ImportError:
    REQUESTS_OK = False

# Canonical indicator engine (unchanged — same as before)
try:
    from .indicators import add_all_indicators
except ImportError:
    try:
        from src.data.indicators import add_all_indicators
    except ImportError:
        add_all_indicators = None

logger = logging.getLogger(__name__)


# ── NSE → Yahoo Finance ticker map ──────────────────────────────────────────
# Yahoo Finance requires ".NS" suffix for NSE stocks
# Index tickers are different (no .NS)

NSE_TO_YAHOO: Dict[str, str] = {
    # ── NIFTY 50 components (common universe) ───────────────────────────────
    "RELIANCE":     "RELIANCE.NS",
    "TCS":          "TCS.NS",
    "HDFCBANK":     "HDFCBANK.NS",
    "INFY":         "INFY.NS",
    "ICICIBANK":    "ICICIBANK.NS",
    "KOTAKBANK":    "KOTAKBANK.NS",
    "HINDUNILVR":   "HINDUNILVR.NS",
    "SBIN":         "SBIN.NS",
    "BHARTIARTL":   "BHARTIARTL.NS",
    "ITC":          "ITC.NS",
    "WIPRO":        "WIPRO.NS",
    "HCLTECH":      "HCLTECH.NS",
    "AXISBANK":     "AXISBANK.NS",
    "LT":           "LT.NS",
    "MARUTI":       "MARUTI.NS",
    "BAJFINANCE":   "BAJFINANCE.NS",
    "BAJAJFINSV":   "BAJAJFINSV.NS",
    "TATAMOTORS":   "TATAMOTORS.NS",
    "TATASTEEL":    "TATASTEEL.NS",
    "SUNPHARMA":    "SUNPHARMA.NS",
    "NTPC":         "NTPC.NS",
    "POWERGRID":    "POWERGRID.NS",
    "TECHM":        "TECHM.NS",
    "ULTRACEMCO":   "ULTRACEMCO.NS",
    "ASIANPAINT":   "ASIANPAINT.NS",
    "HINDALCO":     "HINDALCO.NS",
    "JSWSTEEL":     "JSWSTEEL.NS",
    "ONGC":         "ONGC.NS",
    "COALINDIA":    "COALINDIA.NS",
    "GRASIM":       "GRASIM.NS",
    "DRREDDY":      "DRREDDY.NS",
    "CIPLA":        "CIPLA.NS",
    "DIVISLAB":     "DIVISLAB.NS",
    "VEDL":         "VEDL.NS",
    "ADANIPORTS":   "ADANIPORTS.NS",
    "SIEMENS":      "SIEMENS.NS",
    "NESTLEIND":    "NESTLEIND.NS",
    "BRITANNIA":    "BRITANNIA.NS",
    "M&M":          "M&M.NS",
    "BAJAJ-AUTO":   "BAJAJ-AUTO.NS",
    "HEROMOTOCO":   "HEROMOTOCO.NS",
    "BIOCON":       "BIOCON.NS",
    "DABUR":        "DABUR.NS",
    "MUTHOOTFIN":   "MUTHOOTFIN.NS",
    "CHOLAFIN":     "CHOLAFIN.NS",
    "INDUSTOWER":   "INDUSTOWER.NS",
    "LTIM":         "LTIM.NS",
    # ── Indices (no .NS — special Yahoo tickers) ─────────────────────────────
    "NIFTY50":      "^NSEI",
    "NIFTY":        "^NSEI",
    "BANKNIFTY":    "^NSEBANK",
    "NIFTYBANK":    "^NSEBANK",
    "VIX":          "^INDIAVIX",
    "INDIAVIX":     "^INDIAVIX",
}

# yfinance interval mapping: our interval strings → yfinance format
_YF_INTERVAL: Dict[str, str] = {
    "1min":  "1m",
    "2min":  "2m",
    "5min":  "5m",
    "15min": "15m",
    "30min": "30m",
    "1hour": "1h",
    "1day":  "1d",
    "1wk":   "1wk",
}

# yfinance period for each interval (maximum allowed by Yahoo for free tier)
_YF_PERIOD: Dict[str, str] = {
    "1m":  "7d",
    "2m":  "60d",
    "5m":  "60d",
    "15m": "60d",
    "30m": "60d",
    "1h":  "730d",
    "1d":  "2y",
    "1wk": "5y",
}


def _to_yahoo(symbol: str) -> str:
    """Convert NSE symbol to Yahoo Finance ticker."""
    if symbol in NSE_TO_YAHOO:
        return NSE_TO_YAHOO[symbol]
    # Handle symbols not in map: assume NSE equity
    if symbol.endswith(".NS") or symbol.startswith("^"):
        return symbol
    return symbol + ".NS"


class DataFetcher:
    """
    Market Data Fetcher — Real NSE Data via yfinance

    Public API is identical to the original file.
    All random/simulation code removed. Real data in both PAPER and LIVE modes.

    Usage:
        fetcher = DataFetcher(config)
        data    = fetcher.get_market_data(['RELIANCE', 'TCS'])
        candles = fetcher.get_ohlcv('RELIANCE', interval='15min', bars=100)
    """

    DEFAULT_SYMBOLS = [
        'RELIANCE', 'TCS', 'HDFCBANK', 'INFY', 'ICICIBANK',
        'KOTAKBANK', 'HINDUNILVR', 'SBIN', 'BHARTIARTL', 'ITC'
    ]

    def __init__(self, config: Dict):
        self.config  = config
        self.mode    = config.get('MODE', 'PAPER').upper()
        self.openalgo_url = config.get('OPENALGO_URL', 'http://127.0.0.1:5000')
        self.api_key = config.get('OPENALGO_API_KEY', '')

        # In-memory cache  {symbol: data_dict}
        self._cache:    Dict[str, Dict]      = {}
        self._cache_ts: Dict[str, datetime]  = {}
        self.cache_ttl_seconds = config.get('DATA_CACHE_TTL', 60)

        # OHLCV candle cache keyed by (symbol, interval)
        self._ohlcv_cache:    Dict[tuple, List[Dict]] = {}
        self._ohlcv_cache_ts: Dict[tuple, datetime]   = {}
        self.ohlcv_cache_ttl  = 300   # 5-minute TTL for candles

        if not YFINANCE_OK:
            logger.warning("yfinance not installed. Run: pip install yfinance")
        else:
            logger.info(f"DataFetcher ready — real NSE data via yfinance (mode={self.mode})")

    # ── Public API ────────────────────────────────────────────────────────────

    def get_market_data(
        self,
        symbols: Optional[List[str]] = None,
        include_indicators: bool = True
    ) -> Dict[str, Any]:
        """
        Fetch live market data for a list of symbols.

        Returns:
            {
              'symbols': [...],
              'prices':  {'RELIANCE': 2450.50, ...},
              'data':    {'RELIANCE': {price, atr, rsi, ema20, ...}, ...},
              'timestamp': datetime
            }
        """
        symbols = symbols or self.DEFAULT_SYMBOLS
        now     = datetime.now()

        prices:     Dict[str, float] = {}
        per_symbol: Dict[str, Dict]  = {}

        # Batch-fetch all symbols at once for efficiency
        batch = self._batch_fetch_quotes(symbols)

        for sym in symbols:
            if self._is_cache_valid(sym):
                entry = self._cache[sym]
            else:
                entry = batch.get(sym) or self._fetch_single_quote(sym)
                if entry:
                    self._cache[sym]    = entry
                    self._cache_ts[sym] = now

            if entry:
                prices[sym]     = entry.get('price', 0.0)
                per_symbol[sym] = entry

        return {
            'symbols':   symbols,
            'prices':    prices,
            'data':      per_symbol,
            'timestamp': now,
        }

    def get_ohlcv(
        self,
        symbol:   str,
        interval: str = '15min',
        bars:     int = 100
    ) -> List[Dict]:
        """
        Return OHLCV candles enriched with technical indicators.

        Args:
            symbol:   NSE symbol, e.g. 'RELIANCE'
            interval: '1min' | '5min' | '15min' | '30min' | '1hour' | '1day'
            bars:     number of candles to return (most recent N)

        Returns:
            List of dicts: [{timestamp, open, high, low, close, volume, rsi, ...}]
        """
        cache_key = (symbol.upper(), interval)
        if self._is_ohlcv_cache_valid(cache_key):
            cached = self._ohlcv_cache[cache_key]
            return cached[-bars:] if len(cached) >= bars else cached

        candles = self._fetch_ohlcv_real(symbol, interval, bars)

        # Enrich with canonical indicators
        if add_all_indicators is not None and len(candles) >= 30:
            try:
                df = pd.DataFrame(candles)
                for col in ['open', 'high', 'low', 'close', 'volume']:
                    df[col] = pd.to_numeric(df[col], errors='coerce')
                enriched = add_all_indicators(df)
                candles  = enriched.to_dict('records')
            except Exception as e:
                logger.warning(f"Indicator enrichment failed for {symbol}: {e}")

        self._ohlcv_cache[cache_key]    = candles
        self._ohlcv_cache_ts[cache_key] = datetime.now()

        return candles[-bars:] if len(candles) >= bars else candles

    def get_options_chain(self, symbol: str) -> Optional[Dict]:
        """Fetch options chain — stub (OpenAlgo options endpoint needed for live)."""
        return None

    def clear_cache(self):
        self._cache.clear()
        self._cache_ts.clear()
        self._ohlcv_cache.clear()
        self._ohlcv_cache_ts.clear()
        logger.info("DataFetcher cache cleared")

    # ── Quote fetching ────────────────────────────────────────────────────────

    def _batch_fetch_quotes(self, symbols: List[str]) -> Dict[str, Dict]:
        """
        Fetch current quotes for all symbols in one yfinance call.
        Much faster than fetching one by one.
        """
        if not YFINANCE_OK:
            return {}

        yahoo_tickers = [_to_yahoo(s) for s in symbols]
        result: Dict[str, Dict] = {}

        try:
            # Download 2-day daily data to get current price + basic stats
            tickers_str = " ".join(yahoo_tickers)
            raw = yf.download(
                tickers_str,
                period="5d",
                interval="1d",
                group_by="ticker",
                auto_adjust=True,
                progress=False,
                threads=True,
            )

            for sym, yticker in zip(symbols, yahoo_tickers):
                try:
                    entry = self._parse_batch_quote(sym, yticker, raw, symbols)
                    if entry:
                        result[sym] = entry
                except Exception as e:
                    logger.debug(f"Batch parse failed for {sym}: {e}")

        except Exception as e:
            logger.warning(f"Batch fetch failed: {e} — will fetch individually")

        return result

    def _parse_batch_quote(
        self,
        symbol:  str,
        yticker: str,
        raw:     Any,
        all_syms: List[str]
    ) -> Optional[Dict]:
        """Extract quote from batch download result."""
        try:
            if len(all_syms) == 1:
                df = raw
            else:
                df = raw[yticker] if yticker in raw.columns.get_level_values(0) else None

            if df is None or df.empty:
                return None

            df = df.dropna(subset=['Close'])
            if df.empty:
                return None

            latest = df.iloc[-1]
            prev   = df.iloc[-2] if len(df) >= 2 else latest

            price       = float(latest['Close'])
            prev_close  = float(prev['Close'])
            change_pct  = round((price - prev_close) / prev_close * 100, 2) if prev_close else 0.0

            # Compute ATR from last 14 days if available
            atr = self._compute_atr_from_df(df)

            return self._build_quote_dict(symbol, price, prev_close, change_pct, atr, df)

        except Exception as e:
            logger.debug(f"_parse_batch_quote {symbol}: {e}")
            return None

    def _fetch_single_quote(self, symbol: str) -> Optional[Dict]:
        """Fallback: fetch a single symbol's quote individually."""
        if not YFINANCE_OK:
            return None
        try:
            yticker = _to_yahoo(symbol)
            tk  = yf.Ticker(yticker)
            df  = tk.history(period="5d", interval="1d", auto_adjust=True)

            if df.empty:
                logger.warning(f"No data returned for {symbol} ({yticker})")
                return None

            # Fix for yfinance >= 0.2.x which returns MultiIndex columns like ('Close','RELIANCE.NS')
            if hasattr(df.columns, 'get_level_values'):
                df.columns = df.columns.get_level_values(0)
            df.columns = [str(c).lower() for c in df.columns]
            df = df.dropna(subset=['close'])

            price      = float(df['close'].iloc[-1])
            prev_close = float(df['close'].iloc[-2]) if len(df) >= 2 else price
            change_pct = round((price - prev_close) / prev_close * 100, 2) if prev_close else 0.0
            atr        = self._compute_atr_from_df(df)

            return self._build_quote_dict(symbol, price, prev_close, change_pct, atr, df)

        except Exception as e:
            logger.warning(f"Single quote fetch failed for {symbol}: {e}")
            return None

    def _build_quote_dict(
        self,
        symbol:     str,
        price:      float,
        prev_close: float,
        change_pct: float,
        atr:        float,
        df:         pd.DataFrame,
    ) -> Dict:
        """Build the standard quote dict from raw price data."""
        # Fix for yfinance >= 0.2.x which returns MultiIndex columns like ('Close','RELIANCE.NS')
        if hasattr(df.columns, 'get_level_values'):
            df.columns = df.columns.get_level_values(0)
        df.columns = [str(c).lower() for c in df.columns]

        # Basic rolling stats from last 20 candles
        close  = df['close'].astype(float)
        volume = df['volume'].astype(float) if 'volume' in df.columns else pd.Series([0.0])

        ema20  = float(close.ewm(span=20).mean().iloc[-1])
        ema50  = float(close.ewm(span=50).mean().iloc[-1]) if len(close) >= 50 else ema20
        rsi    = float(self._compute_rsi(close).iloc[-1])

        # MACD
        ema12  = close.ewm(span=12).mean()
        ema26  = close.ewm(span=26).mean()
        macd   = float((ema12 - ema26).iloc[-1])
        signal = float((ema12 - ema26).ewm(span=9).mean().iloc[-1])

        # ADX (simplified)
        adx    = float(self._compute_adx(df).iloc[-1]) if len(df) >= 14 else 20.0

        # VWAP (today's average price as proxy)
        vwap   = float(close.iloc[-5:].mean()) if len(close) >= 5 else price

        # BB
        mid    = close.rolling(20).mean().iloc[-1] if len(close) >= 20 else price
        std    = close.rolling(20).std().iloc[-1]  if len(close) >= 20 else price * 0.01
        bb_upper = float(mid + 2 * std)
        bb_lower = float(mid - 2 * std)

        avg_vol  = float(volume.mean()) if len(volume) > 0 else 0.0
        high_20d = float(close.rolling(min(20, len(close))).max().iloc[-1])
        low_20d  = float(close.rolling(min(20, len(close))).min().iloc[-1])

        india_vix = self._get_vix()

        return {
            'symbol':           symbol,
            'price':            round(price, 2),
            'close':            round(price, 2),
            'open':             round(float(df['open'].iloc[-1]) if 'open' in df.columns else price, 2),
            'high':             round(float(df['high'].iloc[-1]) if 'high' in df.columns else price * 1.01, 2),
            'low':              round(float(df['low'].iloc[-1])  if 'low'  in df.columns else price * 0.99, 2),
            'prev_close':       round(prev_close, 2),
            'price_change_pct': change_pct,
            'volume':           int(volume.iloc[-1]) if len(volume) > 0 else 0,
            'avg_volume':       int(avg_vol),
            'atr':              round(atr, 2),
            'ema20':            round(ema20, 2),
            'ema50':            round(ema50, 2),
            'rsi':              round(rsi, 1),
            'macd':             round(macd, 2),
            'macd_signal':      round(signal, 2),
            'adx':              round(adx, 1),
            'vwap':             round(vwap, 2),
            'bb_upper':         round(bb_upper, 2),
            'bb_lower':         round(bb_lower, 2),
            'new_high_20d':     price >= high_20d * 0.999,
            'new_low_20d':      price <= low_20d  * 1.001,
            'india_vix':        india_vix,
            'source':           'yfinance',
            'fetched_at':       datetime.now().isoformat(),
            'fundamental':      {},   # populated by get_fundamentals() call
        }

    # ── OHLCV fetching ────────────────────────────────────────────────────────

    def _fetch_ohlcv_real(self, symbol: str, interval: str, bars: int) -> List[Dict]:
        """
        Fetch real OHLCV candles from yfinance.
        Falls back to OpenAlgo if api_key is set and mode is LIVE.
        """
        # Try OpenAlgo first if in LIVE mode and API key is set
        if self.mode == 'LIVE' and self.api_key and REQUESTS_OK:
            candles = self._fetch_ohlcv_openalgo(symbol, interval, bars)
            if candles:
                return candles
            logger.warning(f"OpenAlgo fetch failed for {symbol} — falling back to yfinance")

        # yfinance
        return self._fetch_ohlcv_yfinance(symbol, interval, bars)

    def _fetch_ohlcv_yfinance(self, symbol: str, interval: str, bars: int) -> List[Dict]:
        """Fetch candles from yfinance."""
        if not YFINANCE_OK:
            logger.error("yfinance not installed. Run: pip install yfinance")
            return []

        yf_interval = _YF_INTERVAL.get(interval, "15m")
        yf_period   = _YF_PERIOD.get(yf_interval, "60d")
        yticker     = _to_yahoo(symbol)

        try:
            df = yf.download(
                yticker,
                period=yf_period,
                interval=yf_interval,
                auto_adjust=True,
                progress=False,
            )

            if df.empty:
                logger.warning(f"No candle data for {symbol} ({yticker})")
                return []

            # Fix for yfinance >= 0.2.x which returns MultiIndex columns like ('Close','RELIANCE.NS')
            if hasattr(df.columns, 'get_level_values'):
                df.columns = df.columns.get_level_values(0)
            df.columns = [str(c).lower() for c in df.columns]
            df = df.dropna(subset=['close'])
            df = df.tail(max(bars, 200))   # keep enough for indicators

            candles = []
            for ts, row in df.iterrows():
                candles.append({
                    'timestamp': ts.isoformat() if hasattr(ts, 'isoformat') else str(ts),
                    'open':      round(float(row['open']),   2),
                    'high':      round(float(row['high']),   2),
                    'low':       round(float(row['low']),    2),
                    'close':     round(float(row['close']),  2),
                    'volume':    int(row['volume']) if 'volume' in row else 0,
                })

            logger.debug(f"yfinance: {symbol} — {len(candles)} candles ({yf_interval})")
            return candles

        except Exception as e:
            logger.warning(f"yfinance OHLCV failed for {symbol}: {e}")
            return []

    def _fetch_ohlcv_openalgo(self, symbol: str, interval: str, bars: int) -> List[Dict]:
        """
        Fetch candles from OpenAlgo REST API (LIVE mode only).
        Endpoint: POST {openalgo_url}/api/v1/history
        """
        if not REQUESTS_OK:
            return []

        # Map our interval to OpenAlgo format
        oa_interval_map = {
            '1min': '1', '5min': '5', '15min': '15',
            '30min': '30', '1hour': '60', '1day': 'D',
        }
        oa_interval = oa_interval_map.get(interval, '15')

        end   = datetime.now()
        start = end - timedelta(days=90)

        payload = {
            'symbol':    symbol,
            'exchange':  'NSE',
            'interval':  oa_interval,
            'start_date': start.strftime('%Y-%m-%d'),
            'end_date':   end.strftime('%Y-%m-%d'),
        }
        headers = {'X-API-Key': self.api_key, 'Content-Type': 'application/json'}

        try:
            resp = _requests.post(
                f"{self.openalgo_url}/api/v1/history",
                json=payload, headers=headers, timeout=10
            )
            resp.raise_for_status()
            data = resp.json()

            candles = []
            for row in data.get('data', data if isinstance(data, list) else []):
                candles.append({
                    'timestamp': row.get('datetime', row.get('timestamp', '')),
                    'open':      float(row.get('open',   0)),
                    'high':      float(row.get('high',   0)),
                    'low':       float(row.get('low',    0)),
                    'close':     float(row.get('close',  0)),
                    'volume':    int(row.get('volume',   0)),
                })

            logger.debug(f"OpenAlgo: {symbol} — {len(candles)} candles")
            return candles[-bars:]

        except Exception as e:
            logger.warning(f"OpenAlgo fetch failed for {symbol}: {e}")
            return []

    # ── Indicator helpers (used when add_all_indicators not available) ─────────

    @staticmethod
    def _compute_rsi(close: pd.Series, period: int = 14) -> pd.Series:
        delta  = close.diff()
        gain   = delta.clip(lower=0).rolling(period).mean()
        loss   = (-delta.clip(upper=0)).rolling(period).mean()
        rs     = gain / (loss + 1e-9)
        return 100 - (100 / (1 + rs))

    @staticmethod
    def _compute_atr_from_df(df: pd.DataFrame, period: int = 14) -> float:
        try:
            df = df.copy()
            # Fix for yfinance >= 0.2.x which returns MultiIndex columns like ('Close','RELIANCE.NS')
            if hasattr(df.columns, 'get_level_values'):
                df.columns = df.columns.get_level_values(0)
            df.columns = [str(c).lower() for c in df.columns]
            if not all(c in df.columns for c in ['high', 'low', 'close']):
                return 0.0
            high  = df['high'].astype(float)
            low   = df['low'].astype(float)
            close = df['close'].astype(float)
            tr    = pd.concat([
                high - low,
                (high - close.shift()).abs(),
                (low  - close.shift()).abs(),
            ], axis=1).max(axis=1)
            return float(tr.rolling(period).mean().iloc[-1]) if len(tr) >= period else float(tr.mean())
        except Exception:
            return 0.0

    @staticmethod
    def _compute_adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
        try:
            df    = df.copy()
            # Fix for yfinance >= 0.2.x which returns MultiIndex columns like ('Close','RELIANCE.NS')
            if hasattr(df.columns, 'get_level_values'):
                df.columns = df.columns.get_level_values(0)
            df.columns = [str(c).lower() for c in df.columns]
            high  = df['high'].astype(float)
            low   = df['low'].astype(float)
            close = df['close'].astype(float)
            tr    = pd.concat([
                high - low,
                (high - close.shift()).abs(),
                (low  - close.shift()).abs(),
            ], axis=1).max(axis=1)
            atr   = tr.rolling(period).mean()
            dm_p  = (high.diff()).clip(lower=0)
            dm_m  = (-low.diff()).clip(lower=0)
            di_p  = 100 * dm_p.rolling(period).mean() / (atr + 1e-9)
            di_m  = 100 * dm_m.rolling(period).mean() / (atr + 1e-9)
            dx    = 100 * (di_p - di_m).abs() / (di_p + di_m + 1e-9)
            return dx.rolling(period).mean().fillna(20.0)
        except Exception:
            return pd.Series([20.0] * len(df))

    # ── VIX ───────────────────────────────────────────────────────────────────

    _vix_cache: float = 15.0
    _vix_fetched_at: Optional[datetime] = None

    def _get_vix(self) -> float:
        """Fetch India VIX from yfinance (cached for 5 min)."""
        now = datetime.now()
        if (
            self._vix_fetched_at is None
            or (now - DataFetcher._vix_fetched_at).total_seconds() > 300
        ):
            try:
                df = yf.download("^INDIAVIX", period="2d", interval="1d",
                                  auto_adjust=True, progress=False)
                if not df.empty:
                    DataFetcher._vix_cache      = round(float(df['Close'].iloc[-1]), 2)
                    DataFetcher._vix_fetched_at = now
            except Exception:
                pass
        return DataFetcher._vix_cache

    # ── Cache helpers ─────────────────────────────────────────────────────────

    def _is_cache_valid(self, symbol: str) -> bool:
        if symbol not in self._cache:
            return False
        age = (datetime.now() - self._cache_ts[symbol]).total_seconds()
        return age < self.cache_ttl_seconds

    def _is_ohlcv_cache_valid(self, key: tuple) -> bool:
        if key not in self._ohlcv_cache:
            return False
        age = (datetime.now() - self._ohlcv_cache_ts[key]).total_seconds()
        return age < self.ohlcv_cache_ttl

    # ── Kept for backwards compatibility (used by some agent code) ────────────

    def _fetch_single(self, symbol: str, include_indicators: bool = True) -> Dict:
        """Kept for backward compat — delegates to _fetch_single_quote."""
        return self._fetch_single_quote(symbol) or {}

    def _simulate_single(self, symbol: str) -> Dict:
        """
        DEPRECATED — no longer returns random data.
        Now returns real data via yfinance so callers never get fake prices.
        """
        logger.warning(f"_simulate_single called for {symbol} — fetching real data instead")
        return self._fetch_single_quote(symbol) or {}

    def _simulate_ohlcv(self, symbol: str, interval: str, bars: int) -> List[Dict]:
        """
        DEPRECATED — no longer returns random candles.
        Now returns real candles via yfinance.
        """
        logger.warning(f"_simulate_ohlcv called for {symbol} — fetching real data instead")
        return self._fetch_ohlcv_yfinance(symbol, interval, bars)

    def _fetch_live(self, symbol: str, include_indicators: bool = True) -> Dict:
        """LIVE mode single fetch — now implemented."""
        return self._fetch_single_quote(symbol) or {}

    def _fetch_ohlcv_live(self, symbol: str, interval: str, bars: int) -> List[Dict]:
        """LIVE mode OHLCV — now implemented."""
        return self._fetch_ohlcv_real(symbol, interval, bars)


    # ── Fundamentals ─────────────────────────────────────────────────────────

    _fund_cache: Dict[str, Dict] = {}
    _fund_cache_ts: Dict[str, datetime] = {}
    _FUND_TTL = 3600   # fundamentals refresh hourly

    def get_fundamentals(self, symbol: str) -> Dict:
        """
        Fetch fundamental data from yfinance Ticker.info.
        Cached for 1 hour (fundamentals rarely change intraday).

        Returns a dict with keys matching the Fundamental tab:
          pe_ratio, revenue_growth, roe, debt_to_equity,
          market_cap_cr, dividend_yield, week52_high, week52_low,
          industry, sector, company_name, eps, book_value
        """
        # Cache hit
        ts = self._fund_cache_ts.get(symbol)
        if ts and (datetime.now() - ts).total_seconds() < self._FUND_TTL:
            return self._fund_cache.get(symbol, {})

        result: Dict = {}
        if not YFINANCE_OK:
            return result
        try:
            yticker = _to_yahoo(symbol)
            tk      = yf.Ticker(yticker)
            info    = tk.info or {}

            # Price / valuation
            pe  = info.get('trailingPE') or info.get('forwardPE')
            rev = info.get('revenueGrowth')         # decimal, e.g. 0.12 → 12%
            roe = info.get('returnOnEquity')         # decimal
            de  = info.get('debtToEquity')           # raw ratio
            mc  = info.get('marketCap')              # in absolute INR / USD
            dy  = info.get('dividendYield')          # decimal
            h52 = info.get('fiftyTwoWeekHigh')
            l52 = info.get('fiftyTwoWeekLow')
            eps = info.get('trailingEps')
            bv  = info.get('bookValue')
            peg = info.get('pegRatio')
            pb  = info.get('priceToBook')
            curr_ratio = info.get('currentRatio')
            profit_margin = info.get('profitMargins')

            result = {
                'pe_ratio':        round(float(pe), 1)          if pe  else None,
                'revenue_growth':  round(float(rev) * 100, 1)   if rev else None,
                'roe':             round(float(roe) * 100, 1)   if roe else None,
                'debt_to_equity':  round(float(de) / 100, 2)    if de  else None,
                'market_cap_cr':   round(float(mc) / 1e7, 0)    if mc  else None,
                'dividend_yield':  round(float(dy) * 100, 2)    if dy  else None,
                'week52_high':     round(float(h52), 2)          if h52 else None,
                'week52_low':      round(float(l52), 2)          if l52 else None,
                'eps':             round(float(eps), 2)          if eps else None,
                'book_value':      round(float(bv), 2)           if bv  else None,
                'peg_ratio':       round(float(peg), 2)          if peg else None,
                'price_to_book':   round(float(pb), 2)           if pb  else None,
                'current_ratio':   round(float(curr_ratio), 2)   if curr_ratio else None,
                'profit_margin':   round(float(profit_margin)*100,1) if profit_margin else None,
                'industry':        info.get('industry', ''),
                'sector':          info.get('sector', ''),
                'company_name':    info.get('longName', symbol),
                'website':         info.get('website', ''),
                'employees':       info.get('fullTimeEmployees'),
                'description':     (info.get('longBusinessSummary') or '')[:300],
            }
            logger.debug(f"Fundamentals fetched for {symbol}: PE={result.get('pe_ratio')}")
        except Exception as e:
            logger.debug(f"Fundamentals fetch failed for {symbol}: {e}")

        self._fund_cache[symbol]    = result
        self._fund_cache_ts[symbol] = datetime.now()
        return result

    # ── Candle Patterns ───────────────────────────────────────────────────────

    def detect_candle_patterns(self, df: 'pd.DataFrame') -> List[str]:
        """
        Detect common candlestick patterns from an OHLCV DataFrame.
        Returns a list of human-readable pattern names found.
        No TA-Lib required — pure pandas math.
        """
        patterns = []
        if df is None or len(df) < 3:
            return patterns

        try:
            o = df['open'].astype(float)
            h = df['high'].astype(float)
            l = df['low'].astype(float)
            c = df['close'].astype(float)

            body   = (c - o).abs()
            up_wick   = h - c.where(c > o, o)
            down_wick = c.where(c < o, o) - l
            total_range = h - l

            idx = -1   # latest candle
            idx2 = -2  # previous

            # ── Doji ────────────────────────────────────────────────────────
            if total_range.iloc[idx] > 0:
                body_ratio = body.iloc[idx] / total_range.iloc[idx]
                if body_ratio < 0.1:
                    patterns.append("🕯 Doji — indecision / potential reversal")

            # ── Hammer ──────────────────────────────────────────────────────
            if (down_wick.iloc[idx] > 2 * body.iloc[idx] and
                    up_wick.iloc[idx] < body.iloc[idx] and
                    c.iloc[idx] > o.iloc[idx]):
                patterns.append("🔨 Hammer — bullish reversal signal")

            # ── Shooting Star ────────────────────────────────────────────────
            if (up_wick.iloc[idx] > 2 * body.iloc[idx] and
                    down_wick.iloc[idx] < body.iloc[idx] and
                    c.iloc[idx] < o.iloc[idx]):
                patterns.append("⭐ Shooting Star — bearish reversal signal")

            # ── Bullish Engulfing ────────────────────────────────────────────
            if (c.iloc[idx2] < o.iloc[idx2] and       # prev red candle
                    c.iloc[idx] > o.iloc[idx] and      # curr green candle
                    o.iloc[idx] < c.iloc[idx2] and     # opens below prev close
                    c.iloc[idx] > o.iloc[idx2]):        # closes above prev open
                patterns.append("🟢 Bullish Engulfing — strong buy signal")

            # ── Bearish Engulfing ────────────────────────────────────────────
            if (c.iloc[idx2] > o.iloc[idx2] and
                    c.iloc[idx] < o.iloc[idx] and
                    o.iloc[idx] > c.iloc[idx2] and
                    c.iloc[idx] < o.iloc[idx2]):
                patterns.append("🔴 Bearish Engulfing — strong sell signal")

            # ── Morning Star (3-candle) ──────────────────────────────────────
            if len(df) >= 3:
                if (c.iloc[-3] < o.iloc[-3] and          # first: red
                        body.iloc[-2] < body.iloc[-3] * 0.5 and   # second: small
                        c.iloc[-1] > o.iloc[-1] and       # third: green
                        c.iloc[-1] > (o.iloc[-3] + c.iloc[-3]) / 2):
                    patterns.append("🌟 Morning Star — strong bullish reversal")

            # ── Evening Star ─────────────────────────────────────────────────
            if len(df) >= 3:
                if (c.iloc[-3] > o.iloc[-3] and
                        body.iloc[-2] < body.iloc[-3] * 0.5 and
                        c.iloc[-1] < o.iloc[-1] and
                        c.iloc[-1] < (o.iloc[-3] + c.iloc[-3]) / 2):
                    patterns.append("🌇 Evening Star — strong bearish reversal")

            # ── Strong Bullish Candle ────────────────────────────────────────
            if (c.iloc[idx] > o.iloc[idx] and
                    body.iloc[idx] > total_range.iloc[idx] * 0.7):
                patterns.append("💪 Strong Bull Candle — momentum continuation")

            # ── Inside Bar ───────────────────────────────────────────────────
            if (h.iloc[idx] < h.iloc[idx2] and l.iloc[idx] > l.iloc[idx2]):
                patterns.append("📦 Inside Bar — consolidation, breakout pending")

        except Exception as e:
            logger.debug(f"Candle pattern detection error: {e}")

        return patterns

    # ── Volume Analysis ───────────────────────────────────────────────────────

    def get_volume_analysis(self, df: 'pd.DataFrame', price: float) -> Dict:
        """
        Compute volume analysis metrics for a symbol.
        Returns dict with OBV, volume profile, and interpretation.
        """
        result = {
            'obv_trend':     'NEUTRAL',
            'vol_spike':     False,
            'vol_ratio':     1.0,
            'vol_5d_avg':    0,
            'vol_20d_avg':   0,
            'price_vol_confirm': False,
            'accumulation':  False,
            'distribution':  False,
        }
        if df is None or len(df) < 5:
            return result
        try:
            close  = df['close'].astype(float)
            volume = df['volume'].astype(float)

            # Volume ratios
            v5   = float(volume.iloc[-5:].mean())
            v20  = float(volume.iloc[-20:].mean()) if len(volume) >= 20 else v5
            last_vol = float(volume.iloc[-1])
            vol_ratio = round(last_vol / v20, 2) if v20 > 0 else 1.0

            # OBV
            price_diff = close.diff()
            obv_dir    = price_diff.apply(lambda x: 1 if x > 0 else -1 if x < 0 else 0)
            obv        = (volume * obv_dir).cumsum()
            obv_ma5    = obv.rolling(5).mean()
            obv_trend  = 'RISING' if obv.iloc[-1] > obv_ma5.iloc[-1] else 'FALLING'

            # Price-volume confirmation
            price_up   = close.iloc[-1] > close.iloc[-2]
            vol_up     = last_vol > v5
            pv_confirm = (price_up and vol_up) or (not price_up and not vol_up)

            # Accumulation: price stable + high volume
            price_range_5d = abs(float(close.iloc[-1]) - float(close.iloc[-5])) / float(close.iloc[-5]) if len(close) >= 5 else 0
            accumulation = price_range_5d < 0.02 and vol_ratio > 1.3
            distribution = price_range_5d < 0.02 and vol_ratio > 1.3 and obv_trend == 'FALLING'

            result.update({
                'obv_trend':          obv_trend,
                'vol_spike':          vol_ratio > 2.5,
                'vol_ratio':          vol_ratio,
                'vol_5d_avg':         int(v5),
                'vol_20d_avg':        int(v20),
                'last_volume':        int(last_vol),
                'price_vol_confirm':  pv_confirm,
                'accumulation':       accumulation and not distribution,
                'distribution':       distribution,
                'interpretation': (
                    f"Volume {vol_ratio:.1f}× 20-day avg · OBV {obv_trend} · "
                    + ("Price-volume CONFIRMING ✅" if pv_confirm else "Price-volume DIVERGING ⚠️")
                    + (" · ACCUMULATION pattern" if accumulation else "")
                    + (" · DISTRIBUTION pattern" if distribution else "")
                ),
            })
        except Exception as e:
            logger.debug(f"Volume analysis error: {e}")
        return result

    # ── Alternative data sources ──────────────────────────────────────────────

    def get_stooq_price(self, symbol: str) -> Optional[float]:
        """
        Fetch latest price from Stooq (free, no API key, good for NSE).
        Use as validation / fallback when yfinance is rate-limited.
        Stooq ticker format for NSE: RELIANCE.IN
        """
        if not REQUESTS_OK:
            return None
        try:
            import urllib.request
            stooq_sym = f"{symbol.lower()}.in"
            url = f"https://stooq.com/q/d/l/?s={stooq_sym}&i=d"
            with urllib.request.urlopen(url, timeout=5) as r:
                lines = r.read().decode().strip().split("\n")
            if len(lines) < 2:
                return None
            last = lines[-1].split(",")
            return float(last[4]) if len(last) >= 5 else None   # Close column
        except Exception:
            return None

    def get_nse_bhav_copy(self, symbol: str) -> Optional[Dict]:
        """
        NSE Bhav Copy (end-of-day CSV from NSE India).
        Free, official, no auth needed. Useful for exact EOD prices.
        URL: https://nsearchives.nseindia.com/products/content/sec_bhavdata_full.csv
        Only available after ~6 PM IST on trading days.
        Returns: {'close': X, 'volume': Y, 'delivery_pct': Z}
        """
        # Intentionally not implemented in PAPER mode to avoid hitting NSE servers
        # in a loop. Enable manually when needed.
        return None

    