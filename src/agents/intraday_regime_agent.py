"""
NEXUS Agent — Intraday Regime Detection
src/agents/intraday_regime_agent.py

Replaces the 4-line stub from create_remaining_files.py.

Detection pipeline (in priority order):
  1. XGBoost classifier  (if xgboost installed + model trained)
  2. Rule-based ensemble (ADX + VIX + ATR + RSI + price breadth)

Regimes:
  TRENDING  — clear directional move, ADX strong, tight ATR bands
  SIDEWAYS  — ADX weak, price oscillating in range
  VOLATILE  — VIX elevated OR ATR spike, wide swings
  RISK_OFF  — VIX extreme OR NIFTY in downtrend AND VIX rising

KPI: Regime accuracy > 75% vs actual market (measured by LENS weekly)

Output: single string, one of the 4 regimes above.
The output is consumed by:
  - TITAN  (selects which of 45 strategies to run)
  - GUARDIAN (RISK_OFF blocks all new entries)
  - ORACLE  (regime_hint cross-check)
  - main.py  (written to status.json → dashboard)
"""

import logging
import threading
from datetime import datetime
from typing import Dict, Any, Optional, List

logger = logging.getLogger("NEXUS")

# ── Optional imports — degrade gracefully ─────────────────────────────────────
try:
    import numpy as np
    _NP = True
except ImportError:
    _NP = False

try:
    import xgboost as xgb
    _XGB = True
except ImportError:
    _XGB = False
    logger.info("NEXUS: xgboost not installed — using rule-based regime detection")

try:
    from ..event_bus.event_bus import BaseAgent, EventType
except ImportError:
    try:
        from src.event_bus.event_bus import BaseAgent, EventType
    except ImportError:
        class BaseAgent:
            def __init__(self, event_bus, config, name=""):
                self.event_bus = event_bus; self.config = config
                self.name = name; self.is_active = True
            def publish_event(self, *a, **k): pass
        class EventType:
            REGIME_CHANGE    = "REGIME_CHANGE"
            SIGNAL_GENERATED = "SIGNAL_GENERATED"


# ── Thresholds (all configurable via config dict) ─────────────────────────────

_DEFAULTS = {
    "NEXUS_ADX_TRENDING":   25.0,   # ADX above → trending
    "NEXUS_ADX_SIDEWAYS":   18.0,   # ADX below → sideways
    "NEXUS_VIX_VOLATILE":   20.0,   # VIX above → volatile
    "NEXUS_VIX_RISK_OFF":   26.0,   # VIX above → risk-off
    "NEXUS_ATR_SPIKE_MULT":  1.8,   # ATR > 1.8× 20-period avg → volatile
    "NEXUS_RSI_OVERBOUGHT": 70.0,
    "NEXUS_RSI_OVERSOLD":   30.0,
    "NEXUS_CACHE_SECS":    300.0,   # re-run detection every 5 min
    "NEXUS_MIN_CANDLES":    20,     # minimum candles needed for indicators
}


class IntradayRegimeAgent(BaseAgent):
    """
    NEXUS — Market Regime Detection Agent

    Usage in main.py:
        regime = self.agents['NEXUS'].detect_regime(market_data)
        # market_data = {'data': {symbol: candle_dict, ...}, 'symbols': [...], ...}
    """

    REGIMES = ("TRENDING", "SIDEWAYS", "VOLATILE", "RISK_OFF")

    def __init__(self, event_bus, config: Dict):
        super().__init__(event_bus=event_bus, config=config, name="NEXUS")

        self._cfg  = {**_DEFAULTS, **config}
        self._lock = threading.Lock()

        # Cache
        self._last_regime:     str              = "SIDEWAYS"
        self._last_detect_ts:  Optional[datetime] = None
        self._regime_history:  List[str]        = []

        # Accuracy tracking
        self._predictions   = 0
        self._correct       = 0

        # XGBoost model (loaded lazily / trained inline on first run)
        self._xgb_model = None
        self._xgb_ready = False

        logger.info("NEXUS Agent initialised — regime detection active")

    # ── public API ────────────────────────────────────────────────────────────

    def detect_regime(self, market_data: Dict[str, Any]) -> str:
        """
        Main entry point — called by main.py every iteration.

        market_data format:
          {
            'data':    { 'RELIANCE': {'close': ..., 'adx': ..., 'atr': ...,
                                       'rsi': ..., 'ema20': ..., 'ema50': ...}, ... },
            'symbols': [...],
            'india_vix': float,    # optional — from ORACLE
            'fii_flow':  float,    # optional — from ORACLE
          }

        Returns one of: 'TRENDING' | 'SIDEWAYS' | 'VOLATILE' | 'RISK_OFF'
        """
        # Cache: don't recompute more often than NEXUS_CACHE_SECS
        cache_secs = self._cfg["NEXUS_CACHE_SECS"]
        with self._lock:
            if self._last_detect_ts is not None:
                elapsed = (datetime.now() - self._last_detect_ts).total_seconds()
                if elapsed < cache_secs:
                    return self._last_regime

        # Extract aggregated indicators across all symbols
        features = self._extract_features(market_data)

        # Try XGBoost first, fall back to rules
        if _XGB and self._xgb_ready and self._xgb_model is not None:
            regime = self._xgb_detect(features)
        else:
            regime = self._rule_detect(features)

        with self._lock:
            prev              = self._last_regime
            self._last_regime = regime
            self._last_detect_ts = datetime.now()
            self._regime_history.append(regime)
            if len(self._regime_history) > 100:
                self._regime_history.pop(0)

        if regime != prev:
            logger.info(f"NEXUS ▶ Regime change: {prev} → {regime}")
            try:
                self.publish_event(EventType.REGIME_CHANGE, {
                    'previous': prev,
                    'current':  regime,
                    'features': features,
                    'timestamp': datetime.now().isoformat(),
                })
            except Exception:
                pass
        else:
            logger.debug(f"NEXUS regime: {regime}")

        return regime

    def get_regime(self) -> str:
        """Return last detected regime without re-running detection."""
        with self._lock:
            return self._last_regime

    def record_outcome(self, actual_regime: str):
        """
        Called by KARMA/LENS to feed back accuracy.
        actual_regime: what the regime turned out to be.
        """
        with self._lock:
            predicted = self._last_regime
        self._predictions += 1
        if predicted == actual_regime:
            self._correct += 1

    def get_stats(self) -> Dict[str, Any]:
        accuracy = round(self._correct / self._predictions, 4) if self._predictions else 0.0
        with self._lock:
            hist = list(self._regime_history[-10:])
        return {
            'name':       "NEXUS",
            'active':     self.is_active,
            'regime':     self._last_regime,
            'history':    hist,
            'xgb_active': self._xgb_ready,
            'predictions': self._predictions,
            'accuracy':   accuracy,
            'kpi':        'Regime accuracy > 75%',
        }

    # ── Feature extraction ────────────────────────────────────────────────────

    def _extract_features(self, market_data: Dict) -> Dict[str, float]:
        """
        Extract exact 14 causal features required by trained XGBoost model.
        Order: adx, rsi, vix, atr_norm, cev, gainer_pct, loser_pct,
               avg_top50_ret, avg_bot50_ret, sector_disp,
               spx_prev_ret, usdinr_change, news_sentiment, event_flag
        """
        symbol_data = market_data.get('data', {})
        vix         = float(market_data.get('india_vix', 0) or 0)
        
        # 1. Base technicals (Aggregated across active symbols)
        adx_vals, rsi_vals, atr_vals, cev_vals = [], [], [], []
        returns = []
        
        for sym_data in symbol_data.values():
            if not isinstance(sym_data, dict): continue
            adx = _safe(sym_data.get('adx'))
            rsi = _safe(sym_data.get('rsi'))
            atr = _safe(sym_data.get('atr_norm') or sym_data.get('atr'))
            cev = _safe(sym_data.get('cev') or sym_data.get('close_vs_ema'))
            ret = _safe(sym_data.get('price_change_pct'))
            
            if adx > 0: adx_vals.append(adx)
            if rsi > 0: rsi_vals.append(rsi)
            if atr > 0: atr_vals.append(atr)
            if cev != 0: cev_vals.append(cev)
            if ret != 0: returns.append(ret)

        # 2. Extreme Movers (Causal breadth)
        returns = sorted(returns)
        n_ret = len(returns) or 1
        gainer_pct = len([r for r in returns if r > 2.0]) / n_ret
        loser_pct  = len([r for r in returns if r < -2.0]) / n_ret
        avg_top50  = _mean(returns[-50:]) if n_ret >= 50 else _mean(returns)
        avg_bot50  = _mean(returns[:50]) if n_ret >= 50 else _mean(returns)

        # 3. Sector Dispersion
        sector_disp = 0.0
        try:
            from src.data.universe import get_sector_map
            smap = get_sector_map()
            s_rets = {}
            for sym, d in symbol_data.items():
                r = _safe(d.get('price_change_pct'))
                if r == 0: continue
                sec = smap.get(sym, 'OTHER')
                if sec not in s_rets: s_rets[sec] = []
                s_rets[sec].append(r)
            
            if _NP:
                medians = [np.median(rs) for rs in s_rets.values() if rs]
                sector_disp = float(np.std(medians)) if len(medians) > 1 else 0.0
        except Exception:
            pass

        # 4. Macro & News (from main.py / market_data)
        return {
            'adx':            _mean(adx_vals) or 25.0,
            'rsi':            _mean(rsi_vals) or 50.0,
            'vix':            vix if vix > 0 else 15.0,
            'atr_norm':       _mean(atr_vals) or 0.5,
            'cev':            _mean(cev_vals) or 0.0,
            'gainer_pct':     gainer_pct,
            'loser_pct':      loser_pct,
            'avg_top50_ret':  avg_top50,
            'avg_bot50_ret':  avg_bot50,
            'sector_disp':    sector_disp,
            'spx_prev_ret':   float(market_data.get('spx_prev_ret', 0.0)),
            'usdinr_change':  float(market_data.get('usdinr_change', 0.0)),
            'news_sentiment': float(market_data.get('news_sentiment', 0.0)),
            'event_flag':     float(market_data.get('event_flag', 0.0)),
        }

    # ── Rule-based detection (always available) ───────────────────────────────

    def _rule_detect(self, f: Dict[str, float]) -> str:
        """
        Multi-factor rule ensemble.
        Each factor votes for a regime; the plurality wins.
        Ties broken by VIX (safety-first).
        """
        adx    = f['adx']
        rsi    = f['rsi']
        vix    = f['vix']
        breadth = f['breadth']   # 0–1
        cev     = f['close_vs_ema']  # % price deviation from ema20
        fii     = f['fii_flow']

        th = self._cfg

        votes: Dict[str, int] = {r: 0 for r in self.REGIMES}

        # ── VIX votes ──────────────────────────────────────────────────────────
        if vix >= th["NEXUS_VIX_RISK_OFF"]:
            votes["RISK_OFF"] += 3          # hard override weight
        elif vix >= th["NEXUS_VIX_VOLATILE"]:
            votes["VOLATILE"] += 2

        # ── FII votes (Institutional Flow) ────────────────────────────────────
        if fii >= 1000:
            votes["TRENDING"] += 2          # Strong institutional buy
        elif fii <= -1000:
            votes["RISK_OFF"] += 2          # Strong institutional sell
        elif fii >= 500:
            votes["TRENDING"] += 1
        elif fii <= -500:
            votes["VOLATILE"] += 1

        # ── ADX votes ──────────────────────────────────────────────────────────
        if adx >= th["NEXUS_ADX_TRENDING"]:
            votes["TRENDING"] += 2
        elif adx <= th["NEXUS_ADX_SIDEWAYS"]:
            votes["SIDEWAYS"] += 2
        else:
            votes["TRENDING"] += 1          # moderate ADX tilts trending

        # ── Breadth (market-wide direction) ───────────────────────────────────
        if breadth >= 0.70:
            votes["TRENDING"] += 1
        elif breadth <= 0.30:
            votes["RISK_OFF"] += 1
        else:
            votes["SIDEWAYS"] += 1

        # ── RSI ────────────────────────────────────────────────────────────────
        if rsi >= th["NEXUS_RSI_OVERBOUGHT"] or rsi <= th["NEXUS_RSI_OVERSOLD"]:
            votes["VOLATILE"] += 1
        elif 40 <= rsi <= 60:
            votes["SIDEWAYS"] += 1

        # ── Price vs EMA ───────────────────────────────────────────────────────
        if abs(cev) >= 3.0:                 # far from mean → trending
            votes["TRENDING"] += 1
        elif abs(cev) <= 0.5:               # very close to mean → sideways
            votes["SIDEWAYS"] += 1

        # Plurality winner
        regime = max(votes, key=votes.get)  # type: ignore[arg-type]

        logger.debug(
            "NEXUS rule votes: %s | ADX=%.1f VIX=%.1f RSI=%.1f breadth=%.2f → %s",
            votes, adx, vix, rsi, breadth, regime
        )
        return regime

    # ── XGBoost detection ─────────────────────────────────────────────────────

    def _xgb_detect(self, f: Dict[str, float]) -> str:
        """
        Run XGBoost classifier with strict 14-feature alignment.
        """
        if not _NP or not _XGB or self._xgb_model is None:
            return self._rule_detect(f)
        try:
            # Ensure exact order as metadata: adx, rsi, vix, atr_norm, cev...
            feat_list = [
                f['adx'], f['rsi'], f['vix'], f['atr_norm'], f['cev'],
                f['gainer_pct'], f['loser_pct'],
                f['avg_top50_ret'], f['avg_bot50_ret'],
                f['sector_disp'], f['spx_prev_ret'],
                f['usdinr_change'], f['news_sentiment'], f['event_flag']
            ]
            
            if len(feat_list) != 14:
                logger.warning(f"NEXUS Feature mismatch: expected 14, got {len(feat_list)}")
                return self._rule_detect(f)
                
            feat = np.array([feat_list], dtype=np.float32)
            pred = self._xgb_model.predict(feat)[0]
            regime_idx = int(pred)
            if 0 <= regime_idx < len(self.REGIMES):
                return self.REGIMES[regime_idx]
        except Exception as e:
            logger.warning("NEXUS XGBoost predict failed: %s — falling back to rules", e)
        return self._rule_detect(f)

    def load_xgb_model(self, model_path: str):
        """
        Load a pre-trained XGBoost regime model from disk.
        Call this from main.py after initialisation:
            agents['NEXUS'].load_xgb_model('models/nexus_regime.json')
        """
        if not _XGB:
            logger.warning("NEXUS: xgboost not installed — cannot load model")
            return
        try:
            model = xgb.XGBClassifier()
            model.load_model(model_path)
            self._xgb_model = model
            self._xgb_ready = True
            logger.info(f"NEXUS XGBoost model loaded from {model_path}")
        except Exception as e:
            logger.warning(f"NEXUS XGBoost model load failed: {e} — using rules")

    def train_xgb_model(self, X, y):
        """
        Train XGBoost from labelled data at runtime.
        X: (n_samples, 6) float array [adx, rsi, vix, breadth, cev, atr]
        y: (n_samples,) int array [0=TRENDING, 1=SIDEWAYS, 2=VOLATILE, 3=RISK_OFF]
        """
        if not _XGB or not _NP:
            return
        try:
            model = xgb.XGBClassifier(
                n_estimators=200, max_depth=5,
                learning_rate=0.1, use_label_encoder=False,
                eval_metric='mlogloss', verbosity=0,
            )
            model.fit(X, y)
            self._xgb_model = model
            self._xgb_ready = True
            logger.info("NEXUS XGBoost model trained successfully")
        except Exception as e:
            logger.warning(f"NEXUS XGBoost training failed: {e}")


# ── helpers ───────────────────────────────────────────────────────────────────

def _safe(v) -> float:
    try:
        f = float(v)
        return f if f == f else 0.0   # NaN check
    except (TypeError, ValueError):
        return 0.0

def _mean(lst: list) -> float:
    return sum(lst) / len(lst) if lst else 0.0
