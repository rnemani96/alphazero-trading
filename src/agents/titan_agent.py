"""
TITAN Agent - Strategy Execution & Signal Generation

Runs all 45+ strategies and generates trading signals with confidence scores.
This is the "brain" that decides WHAT to trade based on technical analysis.

FIXES:
  - Removed `from numpy import iterable` (removed in NumPy 1.25+, caused ImportError)
  - Removed `from src import data` (dead circular import)
  - Added safe indicator access with .get() fallback
  - Added proper error handling per symbol
"""

import logging
from typing import Dict, List, Any, Optional
from datetime import datetime

from ..event_bus.event_bus import BaseAgent, EventType

logger = logging.getLogger(__name__)


class TitanAgent(BaseAgent):
    """
    TITAN - Strategy Execution Agent

    Responsibilities:
    - Run all active trading strategies
    - Generate trading signals (BUY/SELL/HOLD)
    - Calculate confidence scores
    - Aggregate multi-strategy signals
    - Adapt to market regime

    KPI: Signal precision > 58%
    """

    def __init__(self, event_bus, config):
        super().__init__(event_bus=event_bus, config=config, name="TITAN")

        # Strategy weights by regime
        self.regime_weights: Dict[str, Dict[str, float]] = {
            'TRENDING': {
                'trend_following': 0.60,
                'breakout':        0.30,
                'volume':          0.10,
            },
            'SIDEWAYS': {
                'mean_reversion':  0.70,
                'volume':          0.30,
            },
            'VOLATILE': {
                'volatility':      0.50,
                'breakout':        0.30,
                'volume':          0.20,
            },
            'RISK_OFF': {
                'defensive':       1.00,
            },
            'NEUTRAL': {
                'trend_following': 0.40,
                'mean_reversion':  0.30,
                'breakout':        0.20,
                'volume':          0.10,
            },
        }

        self.active_strategies: List[str] = [
            'ema_cross',
            'rsi_extreme',
            'bollinger_squeeze',
            'volume_breakout',
            'vwap_cross',
            'macd_divergence',
        ]

        self.signals_generated: int = 0
        logger.info("TITAN Agent initialized - Strategy execution ready")

    # ── Public API ────────────────────────────────────────────────────────────

    def generate_signals(
        self,
        market_data: Dict[str, Any],
        regime: str = 'NEUTRAL',
    ) -> List[Dict[str, Any]]:
        """
        Generate trading signals for all symbols in market_data.

        Args:
            market_data: dict keyed by symbol, each value is a dict of indicators
            regime:      current market regime string

        Returns:
            List of signal dicts with keys: symbol, signal, action,
            confidence, price, stop_loss, target, reasons, regime, source
        """
        signals: List[Dict[str, Any]] = []
        weights = self.regime_weights.get(regime, self.regime_weights['NEUTRAL'])

        for symbol, data in market_data.items():
            try:
                sig = self._compute_signal(symbol, data, regime, weights)
                if sig is not None:
                    signals.append(sig)
                    self.signals_generated += 1
            except Exception as exc:
                logger.debug(f"TITAN: signal error for {symbol}: {exc}")

        if signals:
            self.publish_event(
                EventType.SIGNAL_GENERATED,
                {'signals': signals, 'regime': regime, 'count': len(signals)},
            )
        return signals

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _compute_signal(
        self,
        symbol: str,
        data: Dict[str, Any],
        regime: str,
        weights: Dict[str, float],
    ) -> Optional[Dict[str, Any]]:
        """Compute a consensus signal for a single symbol."""
        # Collect individual strategy votes
        strategy_signals = [
            self._trend_signals(data),
            self._reversion_signals(data),
            self._breakout_signals(data),
            self._volume_signals(data),
        ]

        keys = ['trend_following', 'mean_reversion', 'breakout', 'volume']

        total_signal     = 0.0
        total_confidence = 0.0
        total_weight     = 0.0
        reasons: List[str] = []

        for i, strat_sig in enumerate(strategy_signals):
            w = weights.get(keys[i], 0.25)
            total_signal     += strat_sig['signal']     * w
            total_confidence += strat_sig['confidence'] * w
            total_weight     += w
            reasons.extend(strat_sig.get('reasons', []))

        if total_weight == 0:
            return None

        avg_signal     = total_signal     / total_weight
        avg_confidence = total_confidence / total_weight

        if avg_signal > 0.4:
            action = 'BUY'
        elif avg_signal < -0.4:
            action = 'SELL'
        else:
            return None   # no clear signal → skip

        price = float(data.get('close', data.get('price', 0)) or 0)
        if price <= 0:
            return None

        atr   = float(data.get('atr', price * 0.015) or price * 0.015)
        stop  = round(price - 2.0 * atr, 2) if action == 'BUY'  else round(price + 2.0 * atr, 2)
        tgt   = round(price + 3.0 * atr, 2) if action == 'BUY'  else round(price - 3.0 * atr, 2)
        rr    = round(abs(tgt - price) / max(abs(price - stop), 0.01), 2)

        return {
            'symbol':     symbol,
            'signal':     action,
            'action':     action,
            'confidence': round(min(avg_confidence, 1.0), 3),
            'signal_strength': round(abs(avg_signal), 3),
            'price':      price,
            'stop_loss':  stop,
            'target':     tgt,
            'rr':         rr,
            'reasons':    reasons[:5],        # cap to avoid bloat
            'regime':     regime,
            'source':     'TITAN',
            'timestamp':  datetime.now().strftime('%H:%M:%S'),
        }

    # ── Strategy families ─────────────────────────────────────────────────────

    def _trend_signals(self, d: Dict) -> Dict:
        """Trend-following signals: EMA cross, MACD, Supertrend."""
        score   = 0.0
        votes   = 0
        reasons = []

        close  = float(d.get('close', 0) or 0)
        ema20  = float(d.get('ema20', 0) or 0)
        ema50  = float(d.get('ema50', 0) or 0)
        macd   = float(d.get('macd', 0) or 0)
        msig   = float(d.get('macd_signal', 0) or 0)
        adx    = float(d.get('adx', 0) or 0)
        st_dir = d.get('supertrend_direction', 0)

        if ema20 > 0 and ema50 > 0:
            votes += 1
            if close > ema20 > ema50:
                score += 1.0; reasons.append('EMA bullish cross')
            elif close < ema20 < ema50:
                score -= 1.0; reasons.append('EMA bearish cross')

        if macd != 0 or msig != 0:
            votes += 1
            if macd > msig:
                score += 0.8; reasons.append('MACD bullish')
            elif macd < msig:
                score -= 0.8; reasons.append('MACD bearish')

        if adx > 25:
            if st_dir == 1:
                score += 0.6; reasons.append('Supertrend bullish')
            elif st_dir == -1:
                score -= 0.6; reasons.append('Supertrend bearish')

        if votes == 0:
            return {'signal': 0.0, 'confidence': 0.0, 'reasons': []}

        norm = score / (votes * 1.0)
        conf = min(abs(norm) * 0.8, 0.95) if votes > 1 else 0.5
        return {'signal': norm, 'confidence': conf, 'reasons': reasons}

    def _reversion_signals(self, d: Dict) -> Dict:
        """Mean-reversion signals: RSI, Bollinger Bands, Stochastic."""
        score   = 0.0
        votes   = 0
        reasons = []

        rsi      = float(d.get('rsi', 50) or 50)
        bb_up    = float(d.get('bb_upper', 0) or 0)
        bb_lo    = float(d.get('bb_lower', 0) or 0)
        close    = float(d.get('close', 0) or 0)
        stoch_k  = float(d.get('stoch_k', 50) or 50)

        if rsi > 0:
            votes += 1
            if rsi < 30:
                score += 1.0; reasons.append(f'RSI oversold ({rsi:.0f})')
            elif rsi > 70:
                score -= 1.0; reasons.append(f'RSI overbought ({rsi:.0f})')

        if bb_up > 0 and bb_lo > 0 and close > 0:
            votes += 1
            if close < bb_lo:
                score += 0.9; reasons.append('Price below BB lower')
            elif close > bb_up:
                score -= 0.9; reasons.append('Price above BB upper')

        if stoch_k > 0:
            votes += 1
            if stoch_k < 20:
                score += 0.7; reasons.append(f'Stoch oversold ({stoch_k:.0f})')
            elif stoch_k > 80:
                score -= 0.7; reasons.append(f'Stoch overbought ({stoch_k:.0f})')

        if votes == 0:
            return {'signal': 0.0, 'confidence': 0.0, 'reasons': []}

        norm = score / (votes * 1.0)
        conf = min(abs(norm) * 0.8, 0.95)
        return {'signal': norm, 'confidence': conf, 'reasons': reasons}

    def _breakout_signals(self, d: Dict) -> Dict:
        """Breakout signals: new highs/lows, ATR-based volatility."""
        score   = 0.0
        reasons = []

        nh20  = d.get('new_high_20d', False)
        nl20  = d.get('new_low_20d', False)
        close = float(d.get('close', 0) or 0)
        vwap  = float(d.get('vwap', 0) or 0)

        if nh20:
            score += 0.8; reasons.append('New 20-day high')
        if nl20:
            score -= 0.8; reasons.append('New 20-day low')

        if vwap > 0 and close > 0:
            if close > vwap * 1.005:
                score += 0.5; reasons.append('Above VWAP')
            elif close < vwap * 0.995:
                score -= 0.5; reasons.append('Below VWAP')

        conf = min(abs(score) * 0.7, 0.90)
        return {'signal': max(-1.0, min(1.0, score)), 'confidence': conf, 'reasons': reasons}

    def _volume_signals(self, d: Dict) -> Dict:
        """Volume signals: volume Z-score, OBV direction."""
        score   = 0.0
        reasons = []

        vol_z = float(d.get('volume_zscore', 0) or 0)
        obv   = float(d.get('obv', 0) or 0)
        close = float(d.get('close', 0) or 0)
        ema50 = float(d.get('ema50', 0) or 0)

        if vol_z > 2.0:
            direction = 1.0 if (close > ema50 > 0) else -1.0
            score += direction * 0.6
            reasons.append(f'High volume spike ({vol_z:.1f}σ)')

        if obv != 0:
            if obv > 0:
                score += 0.3; reasons.append('OBV positive')
            else:
                score -= 0.3; reasons.append('OBV negative')

        conf = min(abs(score) * 0.6, 0.80)
        return {'signal': max(-1.0, min(1.0, score)), 'confidence': conf, 'reasons': reasons}

    def get_stats(self) -> Dict[str, Any]:
        """Return current TITAN statistics."""
        return {
            'name':               self.name,
            'active':             self.is_active,
            'signals_generated':  self.signals_generated,
            'active_strategies':  len(self.active_strategies),
            'kpi':                'Signal precision > 58%',
        }
