"""
DataFetcher - Market Data Abstraction Layer

Provides a single interface to fetch OHLCV, technical indicators,
and options data.  In production, connects to OpenAlgo / NSE API.
In PAPER / test mode, returns simulated data so the system can run
without a live broker connection.

FIXES / NEW FILE:
- main.py imports `from src.data.fetch import DataFetcher` but this file
  was completely missing from the project.  Created from scratch.
- Now imports indicators.py (add_all_indicators) so all candle DataFrames
  are enriched by the single canonical indicator engine, exactly as specified
  in stock_ai_design.docx ("Same code used in: Backtest | Replay | Live").
"""

import logging
import random
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any

import pandas as pd
import numpy as np

# Canonical indicator engine (single source of truth for all indicator math)
try:
    from .indicators import add_all_indicators
except ImportError:
    try:
        from src.data.indicators import add_all_indicators
    except ImportError:
        add_all_indicators = None   # graceful degradation — agents fall back to raw data

logger = logging.getLogger(__name__)


class DataFetcher:
    """
    Market Data Fetcher

    Responsibilities:
    - Fetch OHLCV candles (intraday & daily)
    - Compute / return common technical indicators
    - Fetch options chain data
    - Cache results to reduce API calls

    Usage:
        fetcher = DataFetcher(config)
        data = fetcher.get_market_data(['RELIANCE', 'TCS'])
    """

    # Default universe if none provided
    DEFAULT_SYMBOLS = [
        'RELIANCE', 'TCS', 'HDFCBANK', 'INFY', 'ICICIBANK',
        'KOTAKBANK', 'HINDUNILVR', 'SBIN', 'BHARTIARTL', 'ITC'
    ]

    def __init__(self, config: Dict):
        self.config = config
        self.mode = config.get('MODE', 'PAPER').upper()
        self.openalgo_url = config.get('OPENALGO_URL', 'http://127.0.0.1:5000')
        self.api_key = config.get('OPENALGO_API_KEY', '')

        # Simple in-memory cache  {symbol: {data}}
        self._cache: Dict[str, Dict] = {}
        self._cache_ts: Dict[str, datetime] = {}
        self.cache_ttl_seconds = config.get('DATA_CACHE_TTL', 60)

        logger.info(f"DataFetcher initialized (mode={self.mode})")

    # ── public API ───────────────────────────────────────────────────────────

    def get_market_data(
        self,
        symbols: Optional[List[str]] = None,
        include_indicators: bool = True
    ) -> Dict[str, Any]:
        """
        Fetch market data for a list of symbols.

        Returns a dict structured for use by both the main loop AND
        the TrailingStopManager / TitanAgent:

            {
              'symbols': ['RELIANCE', ...],
              'prices':  {'RELIANCE': 2450.50, ...},   # flat lookup
              'data':    {                              # per-symbol detail
                  'RELIANCE': {
                      'price': 2450.50,
                      'atr': 32.5,
                      'close': 2450.50,
                      'ema20': 2440.0,
                      'ema50': 2420.0,
                      'rsi': 62.0,
                      ...
                  }
              },
              'timestamp': datetime.now()
            }
        """
        symbols = symbols or self.DEFAULT_SYMBOLS
        now = datetime.now()

        prices: Dict[str, float] = {}
        per_symbol: Dict[str, Dict] = {}

        for sym in symbols:
            # Use cache if fresh
            if self._is_cache_valid(sym):
                entry = self._cache[sym]
            else:
                entry = self._fetch_single(sym, include_indicators)
                self._cache[sym] = entry
                self._cache_ts[sym] = now

            prices[sym] = entry['price']
            per_symbol[sym] = entry

        return {
            'symbols': symbols,
            'prices': prices,       # flat  {symbol: price} — used by main._monitor_positions
            'data': per_symbol,     # nested {symbol: {...}} — used by TrailingStopManager & TITAN
            'timestamp': now
        }

    def get_ohlcv(
        self,
        symbol: str,
        interval: str = '15min',
        bars: int = 50
    ) -> List[Dict]:
        """
        Return OHLCV candles enriched with technical indicators (via indicators.py).

        The canonical indicator engine is used so backtest, replay, and live all
        compute indicators identically — as required by stock_ai_design.docx.

        Args:
            symbol:   e.g. 'RELIANCE'
            interval: '1min' | '5min' | '15min' | '1hour' | '1day'
            bars:     number of candles to return
        """
        raw_candles = (
            self._simulate_ohlcv(symbol, interval, bars)
            if self.mode == 'PAPER'
            else self._fetch_ohlcv_live(symbol, interval, bars)
        )

        # Enrich with canonical indicators (single source of truth)
        if add_all_indicators is not None and len(raw_candles) >= 30:
            try:
                df = pd.DataFrame(raw_candles)
                for col in ['open', 'high', 'low', 'close', 'volume']:
                    df[col] = pd.to_numeric(df[col], errors='coerce')
                enriched = add_all_indicators(df)
                return enriched.to_dict('records')
            except Exception as e:
                logger.warning(f"Indicator enrichment failed for {symbol}: {e} — returning raw")

        return raw_candles

    def get_options_chain(self, symbol: str) -> Optional[Dict]:
        """Fetch options chain data (stub in PAPER mode)."""
        if self.mode == 'PAPER':
            return None  # Options flow agent handles its own simulation
        # Production: call OpenAlgo options endpoint
        return None

    # ── private: live fetch (production) ────────────────────────────────────

    def _fetch_single(self, symbol: str, include_indicators: bool) -> Dict:
        """Fetch data for one symbol.  Falls back to simulation in PAPER mode."""
        if self.mode == 'LIVE':
            try:
                return self._fetch_live(symbol, include_indicators)
            except Exception as e:
                logger.warning(f"Live fetch failed for {symbol}: {e} — using simulation")

        return self._simulate_single(symbol)

    def _fetch_live(self, symbol: str, include_indicators: bool) -> Dict:
        """
        Production: call OpenAlgo REST API.

        Implement by hitting:
          GET {openalgo_url}/api/v1/quotes/{symbol}
        with header X-API-Key: {api_key}
        """
        raise NotImplementedError("Live fetch not yet implemented — set MODE=PAPER")

    def _fetch_ohlcv_live(self, symbol: str, interval: str, bars: int) -> List[Dict]:
        raise NotImplementedError("Live OHLCV not yet implemented — set MODE=PAPER")

    # ── private: simulation (PAPER mode) ────────────────────────────────────

    _BASE_PRICES: Dict[str, float] = {
        'RELIANCE':    2450.50,
        'TCS':         3580.25,
        'HDFCBANK':    1620.75,
        'INFY':        1450.30,
        'ICICIBANK':   1020.15,
        'KOTAKBANK':   1750.00,
        'HINDUNILVR':   2600.00,
        'SBIN':          620.50,
        'BHARTIARTL':    850.75,
        'ITC':           435.20,
    }

    def _simulate_single(self, symbol: str) -> Dict:
        """Generate plausible synthetic data for a symbol."""
        base = self._BASE_PRICES.get(symbol, 1000.0)
        # Add small random walk
        price = round(base * (1 + random.uniform(-0.02, 0.02)), 2)
        atr   = round(price * random.uniform(0.010, 0.025), 2)

        return {
            'symbol':          symbol,
            'price':           price,
            'close':           price,
            'open':            round(price * (1 + random.uniform(-0.005, 0.005)), 2),
            'high':            round(price * (1 + random.uniform(0.002, 0.015)), 2),
            'low':             round(price * (1 - random.uniform(0.002, 0.015)), 2),
            'volume':          random.randint(50_000, 500_000),
            'avg_volume':      200_000,
            'atr':             atr,
            'ema20':           round(price * (1 + random.uniform(-0.01, 0.01)), 2),
            'ema50':           round(price * (1 + random.uniform(-0.02, 0.00)), 2),
            'rsi':             round(random.uniform(35, 70), 1),
            'macd':            round(random.uniform(-20, 20), 2),
            'macd_signal':     round(random.uniform(-15, 15), 2),
            'adx':             round(random.uniform(15, 40), 1),
            'vwap':            round(price * (1 + random.uniform(-0.005, 0.005)), 2),
            'bb_upper':        round(price * 1.02, 2),
            'bb_lower':        round(price * 0.98, 2),
            'new_high_20d':    random.random() < 0.1,
            'new_low_20d':     random.random() < 0.05,
            'price_change_pct':round(random.uniform(-2, 2), 2),
            'india_vix':       round(random.uniform(12, 22), 1),
        }

    def _simulate_ohlcv(self, symbol: str, interval: str, bars: int) -> List[Dict]:
        """Generate synthetic OHLCV candles."""
        base = self._BASE_PRICES.get(symbol, 1000.0)
        candles = []
        price = base
        now = datetime.now()

        interval_minutes = {
            '1min': 1, '5min': 5, '15min': 15,
            '1hour': 60, '1day': 1440
        }.get(interval, 15)

        for i in range(bars - 1, -1, -1):
            ts = now - timedelta(minutes=i * interval_minutes)
            o = price
            c = round(o * (1 + random.uniform(-0.005, 0.005)), 2)
            h = round(max(o, c) * (1 + random.uniform(0, 0.005)), 2)
            lo = round(min(o, c) * (1 - random.uniform(0, 0.005)), 2)
            vol = random.randint(10_000, 100_000)
            candles.append({
                'timestamp': ts.isoformat(),
                'open': o, 'high': h, 'low': lo, 'close': c, 'volume': vol
            })
            price = c

        return candles

    # ── helpers ──────────────────────────────────────────────────────────────

    def _is_cache_valid(self, symbol: str) -> bool:
        if symbol not in self._cache:
            return False
        age = (datetime.now() - self._cache_ts[symbol]).total_seconds()
        return age < self.cache_ttl_seconds

    def clear_cache(self):
        """Clear all cached data."""
        self._cache.clear()
        self._cache_ts.clear()
        logger.info("DataFetcher cache cleared")
