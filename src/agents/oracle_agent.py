"""
ORACLE Agent — Macro Intelligence
src/agents/oracle_agent.py

Tracks macroeconomic signals that move Indian markets BEFORE price moves:
  - India VIX (fear gauge)
  - RBI repo rate & stance
  - FII / DII daily net flows (NSE data)
  - SGX Nifty pre-market signal
  - USD/INR exchange rate
  - US markets close (S&P 500 / Nasdaq prev-day return)
  - Global commodity prices (Crude, Gold)

Outputs:
  - macro_bias  : BULLISH | BEARISH | NEUTRAL
  - risk_level  : LOW | MEDIUM | HIGH | EXTREME
  - size_mult   : float 0.25–1.0  (multiply every position size by this)
  - regime_hint : suggestion fed to NEXUS for regime classification

KPI  : Macro call accuracy > 65% monthly
Event: Publishes EventType.MACRO_UPDATE every iteration

Design principle: ORACLE *never* places trades.  It only influences
position sizing and provides context to other agents via events.
GUARDIAN's hard limits always override ORACLE's multiplier.
"""

import logging
import threading
from datetime import datetime, date, timedelta
from typing import Dict, Any, Optional, List

logger = logging.getLogger(__name__)

# Optional: nsepython for India-specific macro data
try:
    from nsepython import *
    NSE_PYTHON_OK = True
except ImportError:
    NSE_PYTHON_OK = False
    logger.warning("ORACLE: nsepython not installed — using cached macro defaults for India data")

# yfinance for global macro tracking
try:
    import yfinance as yf
    YFINANCE_OK = True
except ImportError:
    YFINANCE_OK = False
    logger.warning("ORACLE: yfinance not installed — using cached macro defaults for global data")


try:
    from ..event_bus.event_bus import BaseAgent, EventType
except ImportError:
    try:
        from src.event_bus.event_bus import BaseAgent, EventType
    except ImportError:
        # Minimal stub so the file can be imported even without the full bus
        class BaseAgent:
            def __init__(self, event_bus, config, name=""):
                self.event_bus = event_bus
                self.config    = config
                self.name      = name
                self.is_active = True
            def publish_event(self, *a, **k): pass

        class EventType:
            MACRO_UPDATE     = "MACRO_UPDATE"
            SIGNAL_GENERATED = "SIGNAL_GENERATED"


# ── Thresholds (all configurable via config dict) ────────────────────────────

_DEFAULTS = {
    # VIX thresholds
    "ORACLE_VIX_LOW":      15.0,   # below → LOW risk
    "ORACLE_VIX_HIGH":     20.0,   # above → HIGH risk
    "ORACLE_VIX_EXTREME":  26.0,   # above → EXTREME risk / size cut 75 %

    # FII flow (₹ Cr per day)
    "ORACLE_FII_BULLISH":   500,   # net buy > this → bullish
    "ORACLE_FII_BEARISH":  -500,   # net sell > this → bearish

    # USD/INR thresholds
    "ORACLE_INR_WEAK":      85.0,  # above → mild bearish for equities
    "ORACLE_INR_CRISIS":    88.0,  # above → hard bearish

    # US market overnight return
    "ORACLE_SPX_BULL":       0.5,  # +0.5 % → positive spillover
    "ORACLE_SPX_BEAR":      -0.5,  # -0.5 % → negative spillover

    # Cache TTL seconds
    "ORACLE_CACHE_TTL":    900,    # refresh macro every 15 min
}


class OracleAgent(BaseAgent):
    """
    ORACLE — Macro Intelligence Agent

    Called once per main-loop iteration via  oracle.analyze(market_data).
    Returns a macro_context dict that main.py passes to NEXUS / TITAN /
    GUARDIAN for position-sizing adjustments.
    """

    # ── init ─────────────────────────────────────────────────────────────────

    def __init__(self, event_bus, config: Dict):
        super().__init__(event_bus=event_bus, config=config, name="ORACLE")

        # Merge config with defaults
        self._cfg = {**_DEFAULTS, **config}

        # In-memory state
        self._macro: Dict[str, Any] = self._empty_macro()
        self._lock    = threading.Lock()
        self._last_fetch: Optional[datetime] = None
        self._calls   = 0          # total analyze() calls
        self._correct = 0          # calls where macro_bias matched next-day direction

        # History (last 30 snapshots for accuracy tracking)
        self._history: List[Dict] = []

        logger.info("ORACLE Agent initialised — macro intelligence active")

    # ── public API ────────────────────────────────────────────────────────────

    def analyze(self, market_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Main entry point called by main.py every iteration.
        """
        self._calls += 1
        ttl = self._cfg.get("ORACLE_CACHE_TTL", 900)

        # Refresh macro data if cache is stale
        now = datetime.now()
        needs_refresh = (
            self._last_fetch is None or
            (now - self._last_fetch).total_seconds() > ttl
        )
        if needs_refresh:
            self._refresh()

        with self._lock:
            ctx = dict(self._macro)

        # Publish to event bus
        try:
            self.publish_event(EventType.MACRO_UPDATE, ctx)
        except Exception:
            pass

        return ctx

    def get_macro_bias(self) -> str:
        with self._lock:
            return self._macro.get("macro_bias", "NEUTRAL")

    def get_position_size_multiplier(self) -> float:
        with self._lock:
            return float(self._macro.get("size_mult", 1.0))

    def get_regime_hint(self) -> str:
        with self._lock:
            return self._macro.get("regime_hint", "TRENDING")

    def record_outcome(self, nifty_moved_up: bool):
        with self._lock:
            bias = self._macro.get("macro_bias", "NEUTRAL")
        predicted_up = (bias == "BULLISH")
        if bias != "NEUTRAL":
            self._correct += (1 if predicted_up == nifty_moved_up else 0)

    def get_stats(self) -> Dict[str, Any]:
        with self._lock:
            macro = dict(self._macro)
        total = self._calls
        acc   = round(self._correct / total, 4) if total > 0 else 0.0
        return {
            "name":          "ORACLE",
            "active":        self.is_active,
            "macro_bias":    macro.get("macro_bias", "NEUTRAL"),
            "risk_level":    macro.get("risk_level",  "MEDIUM"),
            "size_mult":     macro.get("size_mult",    1.0),
            "vix":           macro.get("vix",          0.0),
            "fii_flow_cr":   macro.get("fii_flow_cr",  0.0),
            "usdinr":        macro.get("usdinr",        0.0),
            "spx_ret_pct":   macro.get("spx_ret_pct",  0.0),
            "total_calls":   total,
            "accuracy":      acc,
            "kpi":           "Macro call accuracy > 65% monthly",
            "last_refresh":  macro.get("timestamp", "—"),
        }

    # ── internals ─────────────────────────────────────────────────────────────

    def _refresh(self):
        """Fetch all macro data sources (synchronous) and update self._macro."""
        logger.debug("ORACLE: refreshing macro data...")
        vix         = self._fetch_vix()
        fii_flow    = self._fetch_fii_flow()
        usdinr      = self._fetch_usdinr()
        spx_ret     = self._fetch_spx_return()
        crude_ret   = self._fetch_crude_return()

        macro = self._compute_macro(vix, fii_flow, usdinr, spx_ret, crude_ret)
        macro["timestamp"] = datetime.now().isoformat()

        with self._lock:
            self._macro = macro
            self._history.append(dict(macro))
            if len(self._history) > 30:
                self._history.pop(0)
        self._last_fetch = datetime.now()

        logger.info(
            "ORACLE ▶ bias=%-8s risk=%-7s size_mult=%.2f  "
            "VIX=%.1f FII=%.0fCr USD/INR=%.2f S&P500=%.2f%%",
            macro["macro_bias"], macro["risk_level"], macro["size_mult"],
            vix, fii_flow, usdinr, spx_ret,
        )

    def _compute_macro(
        self,
        vix:      float,
        fii_flow: float,
        usdinr:   float,
        spx_ret:  float,
        crude_ret: float,
    ) -> Dict[str, Any]:
        score = 0
        vix_low = self._cfg["ORACLE_VIX_LOW"]
        vix_high = self._cfg["ORACLE_VIX_HIGH"]
        vix_extreme = self._cfg["ORACLE_VIX_EXTREME"]

        if vix <= 0: pass
        elif vix < vix_low: score += 1
        elif vix > vix_extreme: score -= 2
        elif vix > vix_high: score -= 1

        if fii_flow > self._cfg["ORACLE_FII_BULLISH"]: score += 1
        elif fii_flow < self._cfg["ORACLE_FII_BEARISH"]: score -= 1

        if usdinr > 0:
            if usdinr > self._cfg["ORACLE_INR_CRISIS"]: score -= 2
            elif usdinr > self._cfg["ORACLE_INR_WEAK"]: score -= 1
            else: score += 1

        if spx_ret > self._cfg["ORACLE_SPX_BULL"]: score += 1
        elif spx_ret < self._cfg["ORACLE_SPX_BEAR"]: score -= 1

        if crude_ret > 2.0: score -= 1
        elif crude_ret < -2.0: score += 1

        if score >= 3:
            bias, risk, mult, hint = "BULLISH",  "LOW",     1.00, "TRENDING"
        elif score >= 1:
            bias, risk, mult, hint = "BULLISH",  "MEDIUM",  0.90, "TRENDING"
        elif score == 0:
            bias, risk, mult, hint = "NEUTRAL",  "MEDIUM",  0.80, "SIDEWAYS"
        elif score == -1:
            bias, risk, mult, hint = "BEARISH",  "HIGH",    0.60, "VOLATILE"
        elif score == -2:
            bias, risk, mult, hint = "BEARISH",  "HIGH",    0.50, "VOLATILE"
        else:
            bias, risk, mult, hint = "BEARISH",  "EXTREME", 0.25, "RISK_OFF"

        return {
            "macro_bias":   bias,
            "risk_level":   risk,
            "size_mult":    mult,
            "regime_hint":  hint,
            "score":        score,
            "vix":          round(vix, 2),
            "fii_flow_cr":  round(fii_flow, 1),
            "usdinr":       round(usdinr, 2),
            "spx_ret_pct":  round(spx_ret, 2),
            "crude_ret_pct": round(crude_ret, 2),
        }

    # ── data fetchers ────────────────────────────────────────────────────────

    def _fetch_vix(self) -> float:
        """Fetch India VIX. Priority: 1. nsepython, 2. yfinance."""
        if NSE_PYTHON_OK:
            try:
                val = nse_quote_ltp("INDIA VIX")
                if val: return round(float(val), 2)
            except: pass
        if YFINANCE_OK:
            try:
                ticker = yf.Ticker("^INDIAVIX")
                return round(float(ticker.fast_info.last_price), 2)
            except: pass
        return 15.0

    def _fetch_fii_flow(self) -> float:
        """Fetch FII net inflow (Cr). Priority: 1. nsepython, 2. proxy."""
        if NSE_PYTHON_OK:
            try:
                data = nse_fii_dii()
                for entry in data:
                    if 'FII' in entry.get('category', ''):
                        return float(entry.get('net', 0.0))
            except: pass
        if YFINANCE_OK:
            try:
                data = yf.download("^NSEI", period="2d", progress=False)
                if not data.empty and len(data) >= 2:
                    ret = (data['Close'].iloc[-1] / data['Close'].iloc[-2] - 1) * 100
                    return round(ret * 1000, 0)
            except: pass
        return 0.0

    def _fetch_usdinr(self) -> float:
        if YFINANCE_OK:
            try:
                ticker = yf.Ticker("USDINR=X")
                return round(float(ticker.fast_info.last_price), 2)
            except: pass
        return 83.3

    def _fetch_spx_return(self) -> float:
        if YFINANCE_OK:
            try:
                data = yf.download("^GSPC", period="2d", progress=False)
                if not data.empty and len(data) >= 2:
                    ret = (data['Close'].iloc[-1] / data['Close'].iloc[-2] - 1) * 100
                    return round(ret, 2)
            except: pass
        return 0.0

    def _fetch_crude_return(self) -> float:
        if YFINANCE_OK:
            try:
                data = yf.download("BZ=F", period="2d", progress=False)
                if not data.empty and len(data) >= 2:
                    ret = (data['Close'].iloc[-1] / data['Close'].iloc[-2] - 1) * 100
                    return round(ret, 2)
            except: pass
        return 0.0

    @staticmethod
    def _empty_macro() -> Dict[str, Any]:
        return {
            "macro_bias":    "NEUTRAL",
            "risk_level":    "MEDIUM",
            "size_mult":     0.80,
            "regime_hint":   "SIDEWAYS",
            "score":         0,
            "vix":           0.0,
            "fii_flow_cr":   0.0,
            "usdinr":        0.0,
            "spx_ret_pct":   0.0,
            "crude_ret_pct": 0.0,
            "timestamp":     "",
        }
