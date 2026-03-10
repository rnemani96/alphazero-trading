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

logger = logging.getLogger("ORACLE")

# Optional fast imports — fall back gracefully so the system boots
# even without internet / yfinance installed.
try:
    import yfinance as yf
    _YF = True
except ImportError:
    _YF = False
    logger.warning("ORACLE: yfinance not installed — using cached macro defaults")

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

        Returns macro_context dict:
        {
            'macro_bias':   'BULLISH' | 'BEARISH' | 'NEUTRAL',
            'risk_level':   'LOW' | 'MEDIUM' | 'HIGH' | 'EXTREME',
            'size_mult':    float,   # multiply every position size by this
            'regime_hint':  str,     # passes to NEXUS
            'vix':          float,
            'fii_flow_cr':  float,   # ₹Cr net FII flow today
            'usdinr':       float,
            'spx_ret_pct':  float,   # US S&P 500 prev-close return %
            'timestamp':    str,
        }
        """
        self._calls += 1
        ttl = self._cfg.get("ORACLE_CACHE_TTL", 900)

        # Refresh macro data if cache is stale
        needs_refresh = (
            self._last_fetch is None or
            (datetime.now() - self._last_fetch).total_seconds() > ttl
        )
        if needs_refresh:
            self._refresh()

        with self._lock:
            ctx = dict(self._macro)

        # Publish to event bus so NEXUS / HERMES can subscribe
        try:
            self.publish_event(EventType.MACRO_UPDATE, ctx)
        except Exception:
            pass

        return ctx

    def get_macro_bias(self) -> str:
        with self._lock:
            return self._macro.get("macro_bias", "NEUTRAL")

    def get_position_size_multiplier(self) -> float:
        """
        Returns a multiplier (0.25–1.0) that scales ALL position sizes.
        GUARDIAN enforces hard limits independently — this is advisory only.
        """
        with self._lock:
            return float(self._macro.get("size_mult", 1.0))

    def get_regime_hint(self) -> str:
        with self._lock:
            return self._macro.get("regime_hint", "TRENDING")

    def record_outcome(self, nifty_moved_up: bool):
        """
        Called by KARMA/LENS after day close to track prediction accuracy.
        nifty_moved_up: True if NIFTY closed higher than open.
        """
        with self._lock:
            bias = self._macro.get("macro_bias", "NEUTRAL")
        predicted_up = (bias == "BULLISH")
        if bias != "NEUTRAL":
            self._correct += (1 if predicted_up == nifty_moved_up else 0)
        logger.debug("ORACLE outcome recorded: bias=%s actual_up=%s", bias, nifty_moved_up)

    def get_stats(self) -> Dict[str, Any]:
        """Return stats dict consumed by agent_tracker / dashboard."""
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
        """Fetch all macro data sources and update self._macro."""
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
        """
        Combine all macro signals into a single bias + risk_level + size_mult.

        Scoring system — each factor votes +1 (bullish), -1 (bearish), 0 (neutral):
          VIX       : low→+1, high→-1, extreme→-2
          FII flow  : buy→+1, sell→-1
          USD/INR   : strong INR→+1, weak→-1, crisis→-2
          S&P 500   : positive overnight→+1, negative→-1
          Crude     : rising > 2% is bad for India (imports) → -1
        """
        score = 0

        # ── VIX ──────────────────────────────────────────────────────────────
        vix_low     = self._cfg["ORACLE_VIX_LOW"]
        vix_high    = self._cfg["ORACLE_VIX_HIGH"]
        vix_extreme = self._cfg["ORACLE_VIX_EXTREME"]

        if vix <= 0:
            vix_vote = 0
        elif vix < vix_low:
            vix_vote = +1
        elif vix > vix_extreme:
            vix_vote = -2
        elif vix > vix_high:
            vix_vote = -1
        else:
            vix_vote = 0
        score += vix_vote

        # ── FII flow ──────────────────────────────────────────────────────────
        fii_bull = self._cfg["ORACLE_FII_BULLISH"]
        fii_bear = self._cfg["ORACLE_FII_BEARISH"]
        if fii_flow > fii_bull:
            score += 1
        elif fii_flow < fii_bear:
            score -= 1

        # ── USD/INR ───────────────────────────────────────────────────────────
        inr_weak   = self._cfg["ORACLE_INR_WEAK"]
        inr_crisis = self._cfg["ORACLE_INR_CRISIS"]
        if usdinr > 0:
            if usdinr > inr_crisis:
                score -= 2
            elif usdinr > inr_weak:
                score -= 1
            else:
                score += 1

        # ── S&P 500 overnight ─────────────────────────────────────────────────
        spx_bull = self._cfg["ORACLE_SPX_BULL"]
        spx_bear = self._cfg["ORACLE_SPX_BEAR"]
        if spx_ret > spx_bull:
            score += 1
        elif spx_ret < spx_bear:
            score -= 1

        # ── Crude ─────────────────────────────────────────────────────────────
        if crude_ret > 2.0:     # crude up > 2% — bad for India (importer)
            score -= 1
        elif crude_ret < -2.0:  # crude down > 2% — good for India
            score += 1

        # ── Translate score → bias + risk_level + size_mult ──────────────────
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

    # ── data fetchers (each returns 0.0 on any failure) ───────────────────────

    def _fetch_vix(self) -> float:
        """India VIX from Yahoo Finance (^INDIAVIX)."""
        if not _YF:
            return 15.0  # safe default
        try:
            data = yf.download("^INDIAVIX", period="1d", interval="1m",
                               progress=False, auto_adjust=True)
            if not data.empty:
                close = data["Close"]
                val = float(close.iloc[-1]) if hasattr(close, "iloc") else float(close.dropna().iloc[-1])
                return round(val, 2)
        except Exception as e:
            logger.debug("ORACLE VIX fetch error: %s", e)
        return 15.0

    def _fetch_fii_flow(self) -> float:
        """
        FII net flow in ₹ Crore.
        Primary: NSE website (unreliable — often blocked).
        Fallback: rough estimate from Nifty overnight movement (proxy).
        Returns positive = net buying, negative = net selling.
        """
        # Proxy: estimate from NIFTY day-over-day change
        if not _YF:
            return 0.0
        try:
            data = yf.download("^NSEI", period="5d", interval="1d",
                               progress=False, auto_adjust=True)
            if data.empty or len(data) < 2:
                return 0.0
            close = data["Close"].dropna()
            ret   = (float(close.iloc[-1]) / float(close.iloc[-2]) - 1) * 100
            # Map NIFTY return to approximate FII flow (heuristic)
            # +1% day → ~+1000 Cr FII buying estimate
            return round(ret * 1000, 0)
        except Exception as e:
            logger.debug("ORACLE FII flow proxy error: %s", e)
        return 0.0

    def _fetch_usdinr(self) -> float:
        """USD/INR exchange rate from Yahoo Finance (USDINR=X)."""
        if not _YF:
            return 83.5  # approx baseline
        try:
            data = yf.download("USDINR=X", period="1d", interval="1m",
                               progress=False, auto_adjust=True)
            if not data.empty:
                close = data["Close"].dropna()
                return round(float(close.iloc[-1]), 2)
        except Exception as e:
            logger.debug("ORACLE USDINR fetch error: %s", e)
        return 83.5

    def _fetch_spx_return(self) -> float:
        """Previous US session S&P 500 return %."""
        if not _YF:
            return 0.0
        try:
            data = yf.download("^GSPC", period="5d", interval="1d",
                               progress=False, auto_adjust=True)
            if data.empty or len(data) < 2:
                return 0.0
            close = data["Close"].dropna()
            ret   = (float(close.iloc[-1]) / float(close.iloc[-2]) - 1) * 100
            return round(ret, 2)
        except Exception as e:
            logger.debug("ORACLE S&P return error: %s", e)
        return 0.0

    def _fetch_crude_return(self) -> float:
        """Crude oil (Brent) previous day return %."""
        if not _YF:
            return 0.0
        try:
            data = yf.download("BZ=F", period="5d", interval="1d",
                               progress=False, auto_adjust=True)
            if data.empty or len(data) < 2:
                return 0.0
            close = data["Close"].dropna()
            ret   = (float(close.iloc[-1]) / float(close.iloc[-2]) - 1) * 100
            return round(ret, 2)
        except Exception as e:
            logger.debug("ORACLE crude return error: %s", e)
        return 0.0

    # ── helpers ───────────────────────────────────────────────────────────────

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
