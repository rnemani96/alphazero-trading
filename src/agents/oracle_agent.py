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

"""
ORACLE Agent — Macro Intelligence
Tracks macroeconomic signals affecting Indian markets.

Outputs:
  macro_bias  : BULLISH | BEARISH | NEUTRAL
  risk_level  : LOW | MEDIUM | HIGH | EXTREME
  size_mult   : float multiplier for position sizing
  regime_hint : TRENDING | SIDEWAYS | VOLATILE | RISK_OFF
"""

import logging
import threading
from datetime import datetime
from typing import Dict, Any, Optional, List

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────
# Optional NSE macro data
# ─────────────────────────────────────────────────────────────

try:
    from nsepython import nse_quote_ltp, nse_fii_dii
    NSE_PYTHON_OK = True
except ImportError:
    NSE_PYTHON_OK = False
    logger.warning("ORACLE: nsepython not installed — using fallback data")

# ─────────────────────────────────────────────────────────────
# Optional global macro data
# ─────────────────────────────────────────────────────────────

try:
    import yfinance as yf
    YFINANCE_OK = True
except ImportError:
    YFINANCE_OK = False
    logger.warning("ORACLE: yfinance not installed — using fallback data")

# ─────────────────────────────────────────────────────────────
# Event bus compatibility
# ─────────────────────────────────────────────────────────────

try:
    from ..event_bus.event_bus import BaseAgent, EventType
except ImportError:

    class BaseAgent:
        def __init__(self, event_bus, config, name=""):
            self.event_bus = event_bus
            self.config = config
            self.name = name
            self.is_active = True

        def publish_event(self, *a, **k):
            pass

    class EventType:
        MACRO_UPDATE = "MACRO_UPDATE"


# ─────────────────────────────────────────────────────────────

_DEFAULTS = {
    "ORACLE_VIX_LOW": 15.0,
    "ORACLE_VIX_HIGH": 20.0,
    "ORACLE_VIX_EXTREME": 26.0,
    "ORACLE_FII_BULLISH": 500,
    "ORACLE_FII_BEARISH": -500,
    "ORACLE_INR_WEAK": 85.0,
    "ORACLE_INR_CRISIS": 88.0,
    "ORACLE_SPX_BULL": 0.5,
    "ORACLE_SPX_BEAR": -0.5,
    "ORACLE_CACHE_TTL": 900,
}


class OracleAgent(BaseAgent):

    def __init__(self, event_bus, config: Dict):
        super().__init__(event_bus, config, name="ORACLE")

        self._cfg = {**_DEFAULTS, **config}

        self._macro: Dict[str, Any] = self._empty_macro()
        self._lock = threading.Lock()

        self._last_fetch: Optional[datetime] = None
        self._history: List[Dict] = []

        self._calls = 0
        self._correct = 0

        logger.info("ORACLE Agent initialised — macro intelligence active")

    # ─────────────────────────────────────────────────────────

    def analyze(self, market_data: Dict[str, Any]) -> Dict[str, Any]:

        self._calls += 1
        ttl = self._cfg["ORACLE_CACHE_TTL"]

        now = datetime.now()

        if (
            self._last_fetch is None
            or (now - self._last_fetch).total_seconds() > ttl
        ):
            self._refresh()

        with self._lock:
            ctx = dict(self._macro)

        try:
            self.publish_event(EventType.MACRO_UPDATE, ctx)
        except Exception:
            pass

        return ctx

    # ─────────────────────────────────────────────────────────

    def _refresh(self):

        vix = self._fetch_vix()
        fii = self._fetch_fii_flow()
        usdinr = self._fetch_usdinr()
        spx = self._fetch_spx_return()
        crude = self._fetch_crude_return()

        macro = self._compute_macro(vix, fii, usdinr, spx, crude)
        macro["timestamp"] = datetime.now().isoformat()

        with self._lock:

            self._macro = macro

            self._history.append(macro)

            if len(self._history) > 30:
                self._history.pop(0)

        self._last_fetch = datetime.now()

        logger.info(
            "ORACLE ▶ bias=%s risk=%s size_mult=%.2f",
            macro["macro_bias"],
            macro["risk_level"],
            macro["size_mult"],
        )

    # ─────────────────────────────────────────────────────────

    def _compute_macro(
        self,
        vix: float,
        fii: float,
        usdinr: float,
        spx: float,
        crude: float,
    ) -> Dict[str, Any]:

        score = 0

        if vix < self._cfg["ORACLE_VIX_LOW"]:
            score += 1
        elif vix > self._cfg["ORACLE_VIX_EXTREME"]:
            score -= 2
        elif vix > self._cfg["ORACLE_VIX_HIGH"]:
            score -= 1

        if fii > self._cfg["ORACLE_FII_BULLISH"]:
            score += 1
        elif fii < self._cfg["ORACLE_FII_BEARISH"]:
            score -= 1

        if usdinr > self._cfg["ORACLE_INR_CRISIS"]:
            score -= 2
        elif usdinr > self._cfg["ORACLE_INR_WEAK"]:
            score -= 1
        else:
            score += 1

        if spx > self._cfg["ORACLE_SPX_BULL"]:
            score += 1
        elif spx < self._cfg["ORACLE_SPX_BEAR"]:
            score -= 1

        if crude > 2:
            score -= 1
        elif crude < -2:
            score += 1

        if score >= 3:
            bias, risk, mult, hint = "BULLISH", "LOW", 1.0, "TRENDING"
        elif score >= 1:
            bias, risk, mult, hint = "BULLISH", "MEDIUM", 0.9, "TRENDING"
        elif score == 0:
            bias, risk, mult, hint = "NEUTRAL", "MEDIUM", 0.8, "SIDEWAYS"
        elif score == -1:
            bias, risk, mult, hint = "BEARISH", "HIGH", 0.6, "VOLATILE"
        elif score == -2:
            bias, risk, mult, hint = "BEARISH", "HIGH", 0.5, "VOLATILE"
        else:
            bias, risk, mult, hint = "BEARISH", "EXTREME", 0.25, "RISK_OFF"

        return {
            "macro_bias": bias,
            "risk_level": risk,
            "size_mult": mult,
            "regime_hint": hint,
            "vix": vix,
            "fii_flow_cr": fii,
            "usdinr": usdinr,
            "spx_ret_pct": spx,
            "crude_ret_pct": crude,
        }

    # ─────────────────────────────────────────────────────────
    # DATA SOURCES
    # ─────────────────────────────────────────────────────────

    def _fetch_vix(self):

        if NSE_PYTHON_OK:
            try:
                val = nse_quote_ltp("INDIA VIX")
                if val:
                    return float(val)
            except Exception:
                pass

        if YFINANCE_OK:
            try:
                t = yf.Ticker("^INDIAVIX")
                price = t.fast_info.get("last_price")
                if price:
                    return float(price)
            except Exception:
                pass

        return 15.0

    def _fetch_fii_flow(self):

        if NSE_PYTHON_OK:
            try:
                data = nse_fii_dii()

                for row in data:
                    cat = row.get("category", "")
                    if "FII" in cat:
                        return float(row.get("net", 0))
            except Exception:
                pass

        return 0.0

    def _fetch_usdinr(self):

        if YFINANCE_OK:
            try:
                t = yf.Ticker("USDINR=X")
                price = t.fast_info.get("last_price")
                if price:
                    return float(price)
            except Exception:
                pass

        return 83.3

    def _fetch_spx_return(self):

        if YFINANCE_OK:
            try:
                d = yf.download("^GSPC", period="2d", progress=False)

                if len(d) >= 2:
                    return (
                        (d["Close"].iloc[-1] / d["Close"].iloc[-2] - 1)
                        * 100
                    )
            except Exception:
                pass

        return 0.0

    def _fetch_crude_return(self):

        if YFINANCE_OK:
            try:
                d = yf.download("BZ=F", period="2d", progress=False)

                if len(d) >= 2:
                    return (
                        (d["Close"].iloc[-1] / d["Close"].iloc[-2] - 1)
                        * 100
                    )
            except Exception:
                pass

        return 0.0

    # ─────────────────────────────────────────────────────────

    @staticmethod
    def _empty_macro():

        return {
            "macro_bias": "NEUTRAL",
            "risk_level": "MEDIUM",
            "size_mult": 0.8,
            "regime_hint": "SIDEWAYS",
            "vix": 0.0,
            "fii_flow_cr": 0.0,
            "usdinr": 0.0,
            "spx_ret_pct": 0.0,
            "crude_ret_pct": 0.0,
            "timestamp": "",
        }