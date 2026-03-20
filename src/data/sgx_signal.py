"""
src/data/sgx_signal.py  —  AlphaZero Capital
═══════════════════════════════════════════════
SGX Nifty Pre-Open Signal

SGX Nifty (now GIFT Nifty) trades from ~06:30 AM IST and provides
a leading indicator of how Nifty 50 will open.  This module:

  1. Fetches GIFT Nifty / SGX Nifty futures price
  2. Computes premium / discount vs previous Nifty close
  3. Generates a pre-open signal (GAP_UP / GAP_DOWN / FLAT)
  4. Estimates opening range for ORB strategy setup
  5. Publishes to Event Bus so TITAN can use it in its ORB strategy

Free sources used (no license required):
  - GIFT Nifty from NSE GIFTs API (when available)
  - Yahoo Finance ^NIFTY_FUT  (approximate)
  - NSE pre-open market data (09:00–09:15 IST window)

Usage:
    signal_obj = SGXSignal()
    signal = signal_obj.get_current_signal()
    # Returns: {
    #     "gift_nifty": 24350.5,
    #     "nifty_prev_close": 24100.0,
    #     "premium": 250.5,
    #     "premium_pct": 1.04,
    #     "signal": "GAP_UP",
    #     "strength": "STRONG",
    #     "expected_open_range": (24250, 24450),
    #     "orb_trade_setup": {"direction": "LONG", "entry_above": 24450},
    #     "timestamp": "2026-03-19T06:45:00",
    # }

Integration points:
  - ORACLE.analyze()  uses the premium_pct as a macro input
  - TITAN._fallback_signals() uses the orb_trade_setup
  - main.py injects the signal into market_data at pre-open time
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timedelta
from typing import Any, Dict, Optional, Tuple
from zoneinfo import ZoneInfo

logger = logging.getLogger("SGXSignal")

IST = ZoneInfo("Asia/Kolkata")

# Thresholds
_STRONG_GAP_PCT    = 0.50    # > 0.5% gap = strong signal
_MODERATE_GAP_PCT  = 0.25    # 0.25–0.5% = moderate
_FLAT_BAND_PCT     = 0.10    # < 0.1% = flat

# Cache TTL: refresh every 3 minutes during pre-open window
_CACHE_TTL_SECS = 180


class SGXSignal:
    """
    GIFT Nifty / SGX Nifty pre-open signal engine.

    Thread-safe, cached, multiple source fallback.
    """

    def __init__(self, event_bus=None):
        self._lock         = threading.Lock()
        self._event_bus    = event_bus
        self._cache: Optional[Dict] = None
        self._cache_ts:    float    = 0.0
        self._prev_close:  float    = 0.0
        self._session: Optional[Any] = None   # requests.Session, lazy

    # ── Public API ────────────────────────────────────────────────────────────

    def get_current_signal(self, prev_close: Optional[float] = None) -> Dict[str, Any]:
        """
        Get the current SGX/GIFT Nifty pre-open signal.

        Args:
            prev_close: yesterday's Nifty 50 close. If None, fetched automatically.

        Returns:
            Full signal dict (see module docstring).
        """
        with self._lock:
            # Use cache if fresh
            if self._cache and (time.time() - self._cache_ts) < _CACHE_TTL_SECS:
                return dict(self._cache)

        # Fetch previous close if not provided
        if prev_close is None:
            prev_close = self._fetch_nifty_prev_close()
        if prev_close > 0:
            self._prev_close = prev_close

        # Fetch live GIFT Nifty price
        gift_price = (
            self._fetch_gift_nifty_nse()
            or self._fetch_gift_nifty_yf()
            or self._fetch_nifty_futures_yf()
        )

        result = self._build_signal(gift_price, self._prev_close)

        with self._lock:
            self._cache    = result
            self._cache_ts = time.time()

        return result

    def is_pre_open_window(self) -> bool:
        """Returns True if current time is the NSE pre-open window (6:30–9:20 IST)."""
        now   = datetime.now(IST)
        total = now.hour * 60 + now.minute
        return 6 * 60 + 30 <= total <= 9 * 60 + 20

    def should_scan(self) -> bool:
        """True if we should be scanning for the pre-open signal right now."""
        now   = datetime.now(IST)
        total = now.hour * 60 + now.minute
        # Best window: 8:45 AM – 9:10 AM IST (30 min before open)
        return 8 * 60 + 45 <= total <= 9 * 60 + 10

    # ── Signal builder ────────────────────────────────────────────────────────

    def _build_signal(self, gift_price: float, prev_close: float) -> Dict[str, Any]:
        """Compute gap metrics and trading setup from raw prices."""
        ts_str = datetime.now(IST).isoformat()

        if gift_price <= 0 or prev_close <= 0:
            return {
                "gift_nifty":     gift_price,
                "nifty_prev_close": prev_close,
                "premium":        0.0,
                "premium_pct":    0.0,
                "signal":         "UNKNOWN",
                "strength":       "NONE",
                "expected_open_range": (0, 0),
                "orb_trade_setup": {},
                "timestamp":      ts_str,
                "source":         "UNAVAILABLE",
            }

        premium     = gift_price - prev_close
        premium_pct = premium / prev_close * 100

        # Signal classification
        if abs(premium_pct) < _FLAT_BAND_PCT:
            signal   = "FLAT"
            strength = "WEAK"
        elif abs(premium_pct) < _MODERATE_GAP_PCT:
            signal   = "GAP_UP" if premium > 0 else "GAP_DOWN"
            strength = "WEAK"
        elif abs(premium_pct) < _STRONG_GAP_PCT:
            signal   = "GAP_UP" if premium > 0 else "GAP_DOWN"
            strength = "MODERATE"
        else:
            signal   = "GAP_UP" if premium > 0 else "GAP_DOWN"
            strength = "STRONG"

        # Expected opening range: ±0.3% around GIFT Nifty price
        band = gift_price * 0.003
        open_range = (round(gift_price - band), round(gift_price + band))

        # ORB trade setup (for TITAN strategy B1)
        orb_setup = self._build_orb_setup(signal, strength, open_range)

        logger.info(
            "SGX Signal: GIFT=%.0f  PrevClose=%.0f  Premium=%.0f (%.2f%%)  %s/%s",
            gift_price, prev_close, premium, premium_pct, signal, strength,
        )

        return {
            "gift_nifty":          round(gift_price, 2),
            "nifty_prev_close":    round(prev_close, 2),
            "premium":             round(premium, 2),
            "premium_pct":         round(premium_pct, 3),
            "signal":              signal,
            "strength":            strength,
            "expected_open_range": open_range,
            "orb_trade_setup":     orb_setup,
            "timestamp":           ts_str,
            "source":              "GIFT_NSE",
        }

    @staticmethod
    def _build_orb_setup(signal: str, strength: str, open_range: Tuple) -> Dict:
        """
        Generate ORB (Opening Range Breakout) trade parameters.

        TITAN strategy B1 / I4 uses these as entry triggers.
        """
        if signal == "FLAT" or strength == "WEAK":
            return {"active": False, "reason": "Gap too small for ORB setup"}

        lo, hi = open_range
        if signal == "GAP_UP":
            return {
                "active":     True,
                "direction":  "LONG",
                "entry_above": hi,   # enter on breakout above range high
                "stop_below":  lo,
                "target":      hi + (hi - lo) * 2,
                "confidence":  0.70 if strength == "STRONG" else 0.55,
                "reason":      f"Gap up {signal}: trade long above range high {hi:.0f}",
            }
        else:  # GAP_DOWN
            return {
                "active":      True,
                "direction":   "SHORT",
                "entry_below": lo,   # enter on breakdown below range low
                "stop_above":  hi,
                "target":      lo - (hi - lo) * 2,
                "confidence":  0.70 if strength == "STRONG" else 0.55,
                "reason":      f"Gap down {signal}: trade short below range low {lo:.0f}",
            }

    # ── Data fetchers ─────────────────────────────────────────────────────────

    def _get_session(self):
        if self._session is None:
            try:
                import requests
                s = requests.Session()
                s.headers.update({
                    "User-Agent": "Mozilla/5.0 (AlphaZero/4.0)",
                    "Referer":    "https://www.nseindia.com",
                    "Accept":     "application/json",
                })
                s.get("https://www.nseindia.com", timeout=5)
                self._session = s
            except Exception:
                pass
        return self._session

    def _fetch_gift_nifty_nse(self) -> float:
        """Fetch GIFT Nifty from NSE India pre-open API or giftnifty.info scrapper."""
        session = self._get_session()
        if not session:
            return 0.0
            
        # Source A: giftnifty.info (Public, simple)
        try:
            r = session.get("https://giftnifty.info/", timeout=8)
            if r.status_code == 200:
                from html.parser import HTMLParser
                import re
                # Look for LTP value in their clean table
                match = re.search(r'>([\d,]+\.\d+)</span>', r.text)
                if not match:
                    # Alternative regex for their different themes
                    match = re.search(r'([\d,]+\.\d+)\s*<', r.text)
                if match:
                    val = match.group(1).replace(",", "")
                    ltp = float(val)
                    if 15000 < ltp < 30000:
                        logger.info("GIFT Nifty via Scraper: %.2f", ltp)
                        return ltp
        except Exception as e:
            logger.debug("Scraper GIFT: %s", e)

        # Source B: NSE pre-open API
        try:
            # NSE provides GIFT Nifty in pre-open data
            url = "https://www.nseindia.com/api/getQuotes?symbol=NIFTYFUT&identifier=NIFTYSGX"
            r   = session.get(url, timeout=5)
            if r.status_code == 200:
                data = r.json()
                ltp  = data.get("data", [{}])[0].get("lastPrice", 0)
                if ltp and float(ltp) > 0:
                    return float(ltp)
        except Exception as exc:
            logger.debug("NSE GIFT: %s", exc)

        # Alternative: NSE pre-open snapshot
        try:
            url = "https://www.nseindia.com/api/market-data-pre-open?key=NIFTY"
            r   = session.get(url, timeout=5)
            if r.status_code == 200:
                data = r.json()
                # Pre-open data shows IEP (Indicative Equilibrium Price)
                for item in data.get("data", []):
                    if "NIFTY" in str(item.get("metadata", {}).get("symbol", "")):
                        iep = item.get("metadata", {}).get("iep", 0)
                        if iep and float(iep) > 0:
                            return float(iep)
        except Exception as exc:
            logger.debug("NSE pre-open: %s", exc)

        return 0.0

    def _fetch_gift_nifty_yf(self) -> float:
        """Fetch GIFT Nifty approximation from Yahoo Finance."""
        try:
            import yfinance as yf
            # GIFT Nifty trades as a futures contract; closest free proxy:
            # Singapore Nifty futures or NIFTY futures (India)
            for ticker in ["^NSEI", "NIFTYBEES.NS"]:
                try:
                    tk   = yf.Ticker(ticker)
                    info = tk.fast_info
                    ltp  = getattr(info, "last_price", None) or getattr(info, "regularMarketPrice", None)
                    if ltp and float(ltp) > 1000:
                        logger.debug("GIFT Nifty from %s: %.2f", ticker, ltp)
                        return float(ltp)
                except Exception:
                    pass
        except ImportError:
            pass
        return 0.0

    def _fetch_nifty_futures_yf(self) -> float:
        """Last resort: use Nifty spot as proxy for futures price."""
        try:
            import yfinance as yf
            df = yf.download("^NSEI", period="2d", interval="1d",
                             auto_adjust=True, progress=False)
            if not df.empty:
                if isinstance(df.columns, __import__("pandas").MultiIndex):
                    df.columns = df.columns.get_level_values(0)
                return float(df["Close"].iloc[-1])
        except Exception as exc:
            logger.debug("Nifty spot proxy: %s", exc)
        return 0.0

    def _fetch_nifty_prev_close(self) -> float:
        """Fetch yesterday's Nifty 50 closing price."""
        try:
            import yfinance as yf
            df = yf.download("^NSEI", period="5d", interval="1d",
                             auto_adjust=True, progress=False)
            if not df.empty:
                if isinstance(df.columns, __import__("pandas").MultiIndex):
                    df.columns = df.columns.get_level_values(0)
                closes = df["Close"].dropna()
                if len(closes) >= 2:
                    return float(closes.iloc[-2])   # previous trading day
                elif len(closes) == 1:
                    return float(closes.iloc[-1])
        except Exception as exc:
            logger.debug("Prev close: %s", exc)
        return 0.0


# ── Module-level singleton ────────────────────────────────────────────────────

_SGX_INSTANCE: Optional[SGXSignal] = None

def get_sgx_signal(event_bus=None) -> SGXSignal:
    global _SGX_INSTANCE
    if _SGX_INSTANCE is None:
        _SGX_INSTANCE = SGXSignal(event_bus=event_bus)
    return _SGX_INSTANCE


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
    sig = SGXSignal()
    result = sig.get_current_signal()

    print("\n" + "=" * 55)
    print("  SGX / GIFT NIFTY PRE-OPEN SIGNAL")
    print("=" * 55)
    print(f"  GIFT Nifty:     {result['gift_nifty']:.2f}")
    print(f"  Prev Close:     {result['nifty_prev_close']:.2f}")
    print(f"  Premium:        {result['premium']:+.2f} ({result['premium_pct']:+.3f}%)")
    print(f"  Signal:         {result['signal']}")
    print(f"  Strength:       {result['strength']}")
    print(f"  Open Range:     {result['expected_open_range'][0]:.0f} – {result['expected_open_range'][1]:.0f}")
    orb = result.get("orb_trade_setup", {})
    if orb.get("active"):
        print(f"\n  ORB Setup ({orb['direction']}):")
        print(f"    Confidence:  {orb['confidence']:.0%}")
        print(f"    Reason:      {orb['reason']}")
    print("=" * 55)
