"""
TITAN Agent — 45-Strategy Signal Engine
src/agents/titan_agent.py

Runs all 45 strategies defined in src/titan.py in one batch, then:
  1. Aggregates per-regime weights (TRENDING / SIDEWAYS / VOLATILE / RISK_OFF)
  2. Computes weighted confidence score 0–1 for each symbol
  3. Emits only signals that exceed the minimum confidence threshold
  4. Requires multi-agent agreement flag when NEXUS and HERMES scores are wired in

KPI: Signal precision > 58%

Architecture note:
  Heavy math lives in src/titan.py (TitanStrategyEngine).
  This file is the event-bus-aware agent wrapper.  No indicator code here.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
try:
    from src.event_bus.event_bus import BaseAgent, EventType
except ImportError:
    try:
        from ..event_bus.event_bus import BaseAgent, EventType
    except ImportError:
        # Fallback for static analysis tools
        class BaseAgent:
            def __init__(self, event_bus=None, config=None, name=""):
                self.event_bus = event_bus; self.config = config or {}; self.name = name
                self.is_active = True; self.last_activity = "Initialised"
            def publish_event(self, *a, **k): pass
        class EventType:
            SIGNAL_GENERATED = "signal_generated"

logger = logging.getLogger(__name__)


# ── Lazy-import heavy strategy engine ─────────────────────────────────────────
def _get_engine():
    """Import TitanStrategyEngine only once (lazy — saves startup RAM)."""
    try:
        from src.titan import TitanStrategyEngine
        return TitanStrategyEngine()
    except ImportError:
        try:
            import sys, os
            sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
            from src.titan import TitanStrategyEngine
            return TitanStrategyEngine()
        except ImportError:
            logger.error("TitanStrategyEngine not found — signals will be empty")
            return None


# ── Regime → strategy-category weights ────────────────────────────────────────
_REGIME_WEIGHTS: Dict[str, Dict[str, float]] = {
    'TRENDING': {
        'Trend':          0.50,
        'Breakout':       0.20,
        'Price Action':   0.10,
        'VWAP':           0.10,
        'Volume':         0.10,
        'Mean Reversion': 0.00,
        'Statistical':    0.00,
    },
    'SIDEWAYS': {
        'Trend':          0.10,
        'Mean Reversion': 0.50,
        'Price Action':   0.10,
        'VWAP':           0.15,
        'Volume':         0.15,
        'Breakout':       0.00,
        'Statistical':    0.00,
    },
    'VOLATILE': {
        'Trend':          0.10,
        'Breakout':       0.30,
        'Price Action':   0.10,
        'VWAP':           0.20,
        'Volume':         0.20,
        'Mean Reversion': 0.10,
        'Statistical':    0.00,
    },
    'RISK_OFF': {
        'Trend':          0.00,
        'Breakout':       0.00,
        'VWAP':           0.00,
        'Volume':         0.00,
        'Mean Reversion': 0.00,
        'Statistical':    0.00,
    },
    'NEUTRAL': {
        'Trend':          0.25,
        'Mean Reversion': 0.20,
        'Price Action':   0.10,
        'Breakout':       0.20,
        'VWAP':           0.15,
        'Volume':         0.10,
        'Statistical':    0.00,
    },
}

# Minimum signals that must agree before emitting a trade proposal
_MIN_AGREEMENT    = 1
# Minimum weighted confidence to emit a signal
_MIN_CONFIDENCE   = 0.52


class TitanAgent(BaseAgent):
    """
    TITAN — Strategy Execution Agent.

    Core public method: generate_signals(market_data, regime) → List[signal_dict]

    Each returned dict contains:
      symbol, action (BUY/SELL), confidence (0–1), signal_strength,
      price, atr, stop_loss, target, rr, reasons, strategy_count,
      top_strategy, regime, source, timestamp
    """

    def __init__(self, event_bus, config: Dict[str, Any]):
        super().__init__(event_bus=event_bus, config=config, name="TITAN")

        self._engine           = None          # lazy-initialised on first call
        self._min_confidence   = float(config.get('TITAN_MIN_CONFIDENCE',   _MIN_CONFIDENCE))
        self._min_agreement    = int(config.get('TITAN_MIN_AGREEMENT',      _MIN_AGREEMENT))

        # Block list for upcoming earnings (Risk management via stock selection)
        self.earnings_blocker = None 
        try:
            from src.agents.earnings_calendar_agent import EarningsCalendarAgent
            self.earnings_blocker = EarningsCalendarAgent(event_bus, config)
        except Exception:
            pass

        # Performance tracking
        self.signals_generated  = 0
        self.signals_emitted    = 0
        self.strategy_win_rates: Dict[str, Dict[str, int]] = {}   # {strategy_id: {wins, total}}

        logger.info("TITAN initialised — min_confidence=%.2f  min_agreement=%d",
                    self._min_confidence, self._min_agreement)

    def generate_signals(
        self,
        market_data: Dict[str, Any],
        regime: str,
        nexus_regime: Optional[str] = None,
        hermes_scores: Optional[Dict[str, float]] = None,
        sigma_scores: Optional[Dict[str, float]] = None,
        atlas_scores: Optional[Dict[str, float]] = None,
        headlines: Optional[List[str]] = None,
        lstm_scores: Optional[Dict[str, float]] = None,
        timeframe: str = "15m",
    ) -> List[Dict[str, Any]]:

        """
        Run all 45 strategies over market_data and return actionable signals.

        Args:
            market_data  : {symbol: indicator_dict}
            regime       : regime string from NEXUS
            nexus_regime : optional override (same as regime usually)
            hermes_scores: {symbol: sentiment_score} from HERMES
            sigma_scores : {symbol: momentum_score} from SIGMA
            atlas_scores : {symbol: sector_strength} from ATLAS

        Returns:
            List of signal dicts, each ready for GUARDIAN → MERCURY pipeline.
        """
        if not market_data:
            return []

        effective_regime = nexus_regime or regime

        # Risk-off → no signals at all
        if effective_regime == 'RISK_OFF':
            logger.info("TITAN: RISK_OFF — no signals generated")
            return []

        # Lazy-init the strategy engine
        if self._engine is None:
            self._engine = _get_engine()

        weights = _REGIME_WEIGHTS.get(effective_regime, _REGIME_WEIGHTS['NEUTRAL'])
        signals: List[Dict[str, Any]] = []

        # Dynamic Thresholds based on Market Regime
        dyn_conf, dyn_aggr = self._get_dynamic_thresholds(effective_regime)

        for symbol, ind_data in market_data.items():
            try:
                # ── Risk Blocker: Upcoming Earnings ───────────────────────────
                if self.earnings_blocker:
                    upcoming = self.earnings_blocker.get_upcoming_earnings([symbol], max_days=2)
                    if upcoming:
                        logger.debug("TITAN: skipping %s — EARNINGS RISK (within 2 days)", symbol)
                        continue

                sig = self._process_symbol(
                    symbol, ind_data, effective_regime, weights,
                    float(hermes_scores.get(symbol, 0.0)) if hermes_scores else 0.0,
                    float(sigma_scores.get(symbol, 0.5)) if sigma_scores else 0.5,
                    float(atlas_scores.get(symbol, 0.5)) if atlas_scores else 0.5,
                    dyn_conf, dyn_aggr,
                    extra={
                        'headlines': headlines or [],
                        'lstm_confidence': lstm_scores.get(symbol, 0.5) if lstm_scores else 0.5
                    },
                    timeframe=timeframe,
                )
                if sig:
                    signals.append(sig)
                    self.signals_emitted += 1
            except Exception as exc:
                logger.debug("TITAN: symbol %s error — %s", symbol, exc)

        self.signals_generated += len(market_data)

        if signals:
            # Publish individual events for LENS to track each signal's performance
            for sig in signals:
                self.publish_event(EventType.SIGNAL_GENERATED, {
                    **sig,
                    'source': 'TITAN',
                    'agent': 'TITAN'
                })

            self.publish_event(EventType.SIGNAL_GENERATED, {
                'source':   'TITAN',
                'regime':   effective_regime,
                'count':    len(signals),
                'symbols':  [s['symbol'] for s in signals],
                'timestamp': datetime.now().isoformat(),
            })
            msg = f"TITAN: {len(signals)} signals emitted for {len(market_data)} symbols (regime={effective_regime} conf={dyn_conf:.2f})"
            logger.info(msg)
        else:
            msg = f"TITAN: no signals passed thresholds (regime={effective_regime} conf={dyn_conf:.2f})"
            logger.info(msg)

        return signals

    def _get_dynamic_thresholds(self, regime: str) -> Tuple[float, int]:
        """Logic: TRENDING -> strict; SIDEWAYS -> loose; VOLATILE -> moderate."""
        r = str(regime).upper().strip()
        if r == "TRENDING":
            return 0.50, 2
        elif r == "SIDEWAYS" or r == "NEUTRAL":
            # Bar relaxed: allow more trades in choppy markets if they show momentum
            return 0.15, 1     # Hyper-relaxed from 0.28
        elif r == "VOLATILE":
            return 0.45, 2
        return max(0.28, (getattr(self, '_min_confidence', 0.52) - 0.15)), 1

    def _process_symbol(
        self,
        symbol: str,
        ind_data: Dict[str, Any],
        regime: str,
        weights: Dict[str, float],
        sentiment: float,
        momentum: float,
        sector_strength: float,
        min_conf: float,
        min_aggr: int,
        extra: Dict[str, Any] = None,
        timeframe: str = "15m",
    ) -> Optional[Dict[str, Any]]:
        """Run strategies for one symbol and aggregate into a single signal."""

        price: float = 0.0
        if isinstance(ind_data, pd.DataFrame):
            if ind_data.empty: return None
            price = float(ind_data['close'].iloc[-1])
        elif isinstance(ind_data, dict):
            price = float(ind_data.get('close') or ind_data.get('price') or 0.0)

        if price <= 0:
            return None

        # ── Build DataFrame for TitanStrategyEngine ──────────────────────────
        if self._engine is not None:
            df = self._build_df(ind_data)
            if df is not None and len(df) >= 5:
                raw_signals = self._engine.compute_all(df, symbol, regime, timeframe)
            else:
                raw_signals = []
        else:
            raw_signals = []

        # Fall back to simple indicator-based signals if engine unavailable
        if not raw_signals:
            raw_signals = self._fallback_signals(ind_data)

        if not raw_signals:
            return None

        # ── Aggregate by regime weights ───────────────────────────────────────
        buy_score: float  = 0.0
        sell_score: float = 0.0
        total_w    = 0.0
        reasons: List[str] = []
        top_strategy: str  = ''
        best_conf  = 0.0

        for sig in raw_signals:
            cat = getattr(sig, 'category', 'Trend')
            w   = weights.get(cat, 0.15)
            if w == 0:
                continue
            c = getattr(sig, 'confidence', 0.5)
            s = getattr(sig, 'signal', 0)
            total_w += w
            if s > 0:
                buy_score  += c * w
            elif s < 0:
                sell_score += c * w
            if c > best_conf:
                best_conf    = c
                top_strategy = getattr(sig, 'strategy_id', '')
                reasons.append(getattr(sig, 'reason', ''))

        # If no weight contributed at all (all zero-weight categories), give equal weight
        if total_w < 1e-9:
            total_w = max(1e-9, len([s for s in raw_signals if getattr(s, 'signal', 0) != 0]) * 0.15)
            if total_w < 1e-9:
                return None

        buy_conf  = buy_score  / total_w
        sell_conf = sell_score / total_w

        # ── Cross-Agent Quality Gate ──────────────────────────────────────────
        # In non-trending markets, we require confirmation from other agents 
        # to ensure we are picking the 'Best of the Best' stocks.
        if regime in ('SIDEWAYS', 'VOLATILE', 'NEUTRAL'):
            # Filter 1: Sentiment (HERMES) - Must be at least slightly negative or better
            if sentiment < -0.1: # Relaxed from 0.0
                return None
            # Filter 2: Momentum (SIGMA) - Relaxed threshold to capture emerging leaders
            if momentum < 0.35: # Relaxed from 0.45
                return None
            # Filter 3: Sector (ATLAS) - Relaxed threshold
            if sector_strength < 0.35: # Relaxed from 0.45
                return None

        # ── Signal Boosting Logic (Reward High-Quality Agreement) ─────────────
        conviction = 0.0
        if sentiment > 0.3:       conviction += 0.05   # HERMES Strong Bullish
        if momentum > 0.7:        conviction += 0.05   # SIGMA High Momentum
        if sector_strength > 0.7: conviction += 0.05   # ATLAS Strong Sector
        
        # ── Requirement #9: News Catalyst Matcher ───────
        ctx = extra or {}
        news_headlines = " ".join(ctx.get('headlines', [])).upper()
        catalysts = ['ORDER', 'DEAL', 'CONTRACT', 'PROFIT', 'DIVIDEND', 'AWARD', 'EXPANSION']
        if any(cat in news_headlines for cat in catalysts):
            conviction += 0.10  # 10% boost for 'Fundamental Why'
            reasons.append(f"Catalyst: Detected news keyword match.")

        # ── Requirement #9: LSTM Pattern Recognition ───────
        lstm_score = ctx.get('lstm_confidence', 0.5)
        if lstm_score > 0.8:
            conviction += 0.10
            reasons.append("Pattern: LSTM detects strong geometric sequence.")

        # Aggregate Result
        buy_conf  = min(1.0, buy_conf + conviction)
        sell_conf = min(1.0, sell_conf + conviction)

        # ── Agreement check ───────────────────────────────────────────────────
        buy_count  = sum(1 for s in raw_signals if getattr(s, 'signal', 0) > 0
                         and getattr(s, 'confidence', 0) >= 0.45)
        sell_count = sum(1 for s in raw_signals if getattr(s, 'signal', 0) < 0
                         and getattr(s, 'confidence', 0) >= 0.45)

        if buy_conf >= sell_conf and (buy_conf > 0.5 or buy_count >= min_aggr):
            if buy_conf  < min_conf: return None
            if buy_count  < min_aggr: return None
            action = 'BUY'
            confidence = buy_conf
        else:
            if sell_conf < min_conf: return None
            if sell_count < min_aggr: return None
            action = 'SELL'
            confidence = sell_conf

        # ── Position sizing inputs ────────────────────────────────────────────
        atr_val = ind_data.get('atr') if isinstance(ind_data, dict) else (ind_data['atr'].iloc[-1] if hasattr(ind_data, 'columns') and 'atr' in ind_data.columns else None)
        atr: float = float(atr_val) if atr_val is not None else float(price * 0.02)
        if atr <= 0:
            atr = float(price * 0.02)
        
        # BUY: target above entry, SL below; SELL: target below entry, SL above
        if action == 'BUY':
            stop_loss: float = round(float(price - 1.5 * atr), 2)
            target: float    = round(float(price + 3.0 * atr), 2)
        else:
            stop_loss: float = round(float(price + 1.5 * atr), 2)
            target: float    = round(float(price - 3.0 * atr), 2)

        # Sanity check: ensure target is on the right side of entry price
        if action == 'BUY' and target <= price:
            target = round(price * 1.06, 2)   # default 6% target
        if action == 'SELL' and target >= price:
            target = round(price * 0.94, 2)   # default 6% short target

        risk: float   = abs(price - stop_loss)
        reward: float = abs(target - price)
        rr: float     = round(float(reward / risk), 2) if risk > 0 else 0.0

        # Minimum R:R filter — greatly relaxed per USER REQUEST to capture momentum
        min_rr = 0.5 if regime in ('SIDEWAYS', 'NEUTRAL') else 1.0
        if rr < min_rr:
            return None

        return {
            'symbol':         symbol,
            'action':         action,
            'signal':         action,
            'confidence':     round(float(confidence), 3),
            'signal_strength': round(float(confidence), 3),
            'price':          price,
            'entry_price':    price,
            'atr':            round(float(atr), 2),
            'stop_loss':      stop_loss,
            'target':         target,
            'rr':             rr,
            'strategy_count': len(raw_signals),
            'buy_count':      buy_count,
            'sell_count':     sell_count,
            'top_strategy':   top_strategy,
            'reasons':        reasons[:4],
            'regime':         regime,
            'sentiment':      round(sentiment, 3),
            'source':         'TITAN',
            'trade_type':     'INTRADAY' if timeframe == '5m' else 'SWING',
            'timestamp':      datetime.now().strftime('%H:%M:%S'),
        }

    def _build_df(self, ind_data: Any) -> Optional[pd.DataFrame]:
        """Build a DataFrame from indicator data so TitanStrategyEngine can run."""
        # Case 1: Already a DataFrame (most efficient)
        if isinstance(ind_data, pd.DataFrame):
            if ind_data.empty: return None
            # Ensure required columns exist, even if as placeholders
            for col in ['open', 'high', 'low', 'close', 'volume']:
                if col not in ind_data.columns:
                    ind_data[col] = ind_data.get('close', 0)
            return ind_data

        # Case 2: List of dicts (historical data)
        if isinstance(ind_data, list):
            if not ind_data: return None
            df = pd.DataFrame(ind_data)
            return df

        # Case 3: Single dict snapshot (legacy / fallback)
        if isinstance(ind_data, dict):
            required = ['close']
            if not all(k in ind_data for k in required):
                return None
            row = {
                'open':   ind_data.get('open',   ind_data['close']),
                'high':   ind_data.get('high',   ind_data['close']),
                'low':    ind_data.get('low',    ind_data['close']),
                'close':  ind_data['close'],
                'volume': ind_data.get('volume', 0),
            }
            # Add all other indicators in the dict as columns (e.g. rsi, ema20)
            for k, v in ind_data.items():
                if k not in row: row[k] = v
            return pd.DataFrame([row])

        return None

    def _fallback_signals(self, d: Dict[str, Any]) -> list:
        """Simple rule-based fallback when TitanStrategyEngine is unavailable."""
        class _Sig:
            def __init__(self, sig, conf, cat, reason, sid):
                self.signal     = sig
                self.confidence = conf
                self.category   = cat
                self.reason     = reason
                self.strategy_id = sid

        sigs = []
        close  = float(d.get('close', 0) or 0)
        ema20  = float(d.get('ema20', 0) or 0)
        ema50  = float(d.get('ema50', 0) or 0)
        rsi    = float(d.get('rsi',  50) or 50)
        macd   = float(d.get('macd',  0) or 0)
        msig   = float(d.get('macd_signal', 0) or 0)
        vwap   = float(d.get('vwap',  0) or 0)
        vol_z  = float(d.get('volume_zscore', 0) or 0)
        bb_up  = float(d.get('bb_upper', 0) or 0)
        bb_lo  = float(d.get('bb_lower', 0) or 0)
        adx    = float(d.get('adx', 0) or 0)

        if close <= 0:
            return sigs

        # EMA cross
        if ema20 > 0 and ema50 > 0:
            if close > ema20 > ema50:
                gap = (ema20 - ema50) / ema50
                sigs.append(_Sig(1, min(0.8, 0.55 + gap * 5), 'Trend',
                                 f'EMA bull cross gap={gap:.2%}', 'T1'))
            elif close < ema20 < ema50:
                sigs.append(_Sig(-1, 0.65, 'Trend', 'EMA bear cross', 'T1'))

        # RSI
        if rsi < 30:
            sigs.append(_Sig(1, 0.70, 'Mean Reversion', f'RSI oversold {rsi:.0f}', 'M1'))
        elif rsi > 70:
            sigs.append(_Sig(-1, 0.70, 'Mean Reversion', f'RSI overbought {rsi:.0f}', 'M1'))

        # MACD
        if macd > msig and macd > 0:
            sigs.append(_Sig(1, 0.60, 'Trend', 'MACD bullish', 'T4'))
        elif macd < msig and macd < 0:
            sigs.append(_Sig(-1, 0.60, 'Trend', 'MACD bearish', 'T4'))

        # VWAP
        if vwap > 0:
            dev = (close - vwap) / vwap
            if close > vwap * 1.003:
                sigs.append(_Sig(1, min(0.72, 0.55 + abs(dev) * 5), 'VWAP', 'Above VWAP', 'V1'))
            elif close < vwap * 0.997:
                sigs.append(_Sig(-1, min(0.72, 0.55 + abs(dev) * 5), 'VWAP', 'Below VWAP', 'V1'))

        # BB bounce
        if bb_up > 0 and bb_lo > 0:
            if close < bb_lo:
                sigs.append(_Sig(1, 0.68, 'Mean Reversion', 'Below BB lower', 'M2'))
            elif close > bb_up:
                sigs.append(_Sig(-1, 0.68, 'Mean Reversion', 'Above BB upper', 'M2'))

        # ADX strength
        if adx > 30:
            if ema20 > ema50 and close > ema20:
                sigs.append(_Sig(1, 0.65, 'Trend', f'ADX strong trend {adx:.0f}', 'T5'))
            elif ema20 < ema50 and close < ema20:
                sigs.append(_Sig(-1, 0.65, 'Trend', f'ADX strong downtrend {adx:.0f}', 'T5'))

        # Volume spike confirmation
        if vol_z > 2.0 and close > ema20:
            sigs.append(_Sig(1, 0.60, 'Volume', f'Vol spike {vol_z:.1f}σ bullish', 'VL2'))
        elif vol_z > 2.0 and close < ema20:
            sigs.append(_Sig(-1, 0.60, 'Volume', f'Vol spike {vol_z:.1f}σ bearish', 'VL2'))

        return sigs

    # ── Learning feedback ─────────────────────────────────────────────────────

    def record_outcome(self, strategy_id: str, won: bool):
        """Called by KARMA/LENS to track strategy accuracy."""
        if strategy_id not in self.strategy_win_rates:
            self.strategy_win_rates[strategy_id] = {'wins': 0, 'total': 0}
        self.strategy_win_rates[strategy_id]['total'] += 1
        if won:
            self.strategy_win_rates[strategy_id]['wins'] += 1

    def get_stats(self) -> Dict[str, Any]:
        total_pred = sum(v['total'] for v in self.strategy_win_rates.values())
        total_wins  = sum(v['wins']  for v in self.strategy_win_rates.values())
        return {
            'name':              self.name,
            'active':            self.is_active,
            'signals_generated': self.signals_generated,
            'signals_emitted':   self.signals_emitted,
            'strategy_count':    45,
            'overall_win_rate':  round(total_wins / max(total_pred, 1), 3),
            'kpi':               'Signal precision > 58%',
            'last_activity':     self.last_activity,
        }
