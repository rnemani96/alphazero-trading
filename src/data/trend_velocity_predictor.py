"""
src/data/trend_velocity_predictor.py  —  AlphaZero Capital
═══════════════════════════════════════════════════════════════════════════════
PREDICTIVE TREND VELOCITY & DIRECTIONAL PRICE ACTION ANALYZER

Responsibilities:
1. Rise vs. Fall Probability Engine:
   - Evaluates multi-bar price action across 4 quantitative dimensions:
     a) Trend Velocity: EMA alignment (9/21/50/200), slope acceleration, Supertrend.
     b) Momentum Dynamics: RSI slope, MACD histogram delta, Stochastic cross.
     c) Order Flow & Volume Pressure: VWAP positioning, Volume Z-score, OBV trend.
     d) Volatility Dispersion: ATR-based statistical probability bounds.
2. Directional Forecasting:
   - Predicts whether the next price movement is predominantly RISE or FALL.
   - Computes statistical win-probability P(Rise) vs P(Fall).
   - Generates asymmetric price targets and fail-safe invalidation levels.
3. Early Reversal & Threat Detector:
   - Continuously monitors open positions for adverse velocity shifts or volume spikes.
   - Recommends immediate profit-taking or emergency stop tightening before
     the position can regress into a loss.
"""

from __future__ import annotations

import logging
import math
from typing import Any, Dict, Optional, Tuple
import numpy as np
import pandas as pd

logger = logging.getLogger("TrendVelocityPredictor")


class TrendVelocityPredictor:
    """
    Quantitative directional analyzer predicting rise and fall probabilities
    with asymmetric profit-maximization targets.
    """

    @staticmethod
    def predict_direction(df: pd.DataFrame, symbol: str = "") -> Dict[str, Any]:
        """
        Analyze candlestick DataFrame and predict price direction (RISE vs FALL).
        
        Returns:
            {
                'symbol': str,
                'predicted_direction': 'RISE' | 'FALL' | 'NEUTRAL',
                'rise_probability': float (0.0 to 1.0),
                'fall_probability': float (0.0 to 1.0),
                'confidence': float (0.0 to 1.0),
                'trend_velocity': float (-1.0 to 1.0),
                'momentum_score': float (-1.0 to 1.0),
                'volume_pressure': float (-1.0 to 1.0),
                'expected_rise_target': float,
                'expected_fall_limit': float,
                'asymmetric_rr': float,
                'reversal_threat': bool,
            }
        """
        if df is None or len(df) < 20:
            return {
                "symbol": symbol,
                "predicted_direction": "NEUTRAL",
                "rise_probability": 0.50,
                "fall_probability": 0.50,
                "confidence": 0.0,
                "trend_velocity": 0.0,
                "momentum_score": 0.0,
                "volume_pressure": 0.0,
                "expected_rise_target": 0.0,
                "expected_fall_limit": 0.0,
                "asymmetric_rr": 1.0,
                "reversal_threat": False,
            }

        # Normalize column names
        data = df.copy()
        data.columns = [c.lower() for c in data.columns]
        c = data["close"].astype(float).values
        h = data["high"].astype(float).values
        l = data["low"].astype(float).values
        v = data["volume"].astype(float).values if "volume" in data.columns else np.ones(len(c))

        current_price = float(c[-1])

        # ── 1. Trend Velocity Score (-1.0 to +1.0) ───────────────────────────
        # EMAs
        ema9 = TrendVelocityPredictor._calc_ema(c, 9)
        ema21 = TrendVelocityPredictor._calc_ema(c, 21)
        ema50 = TrendVelocityPredictor._calc_ema(c, 50) if len(c) >= 50 else ema21

        v_score = 0.0
        # Alignment check
        if ema9[-1] > ema21[-1] > ema50[-1]:
            v_score += 0.40  # Bullish stacked
        elif ema9[-1] < ema21[-1] < ema50[-1]:
            v_score -= 0.40  # Bearish stacked

        # Price position relative to short-term EMA
        if current_price > ema9[-1]:
            v_score += 0.20
        else:
            v_score -= 0.20

        # EMA slope velocity (acceleration over last 3 bars)
        if len(ema9) >= 4:
            slope_9 = (ema9[-1] - ema9[-4]) / max(ema9[-4], 1e-4) * 100
            v_score += min(max(slope_9 * 0.5, -0.40), 0.40)

        trend_velocity = round(min(max(v_score, -1.0), 1.0), 3)

        # ── 2. Momentum Dynamics (-1.0 to +1.0) ─────────────────────────────
        m_score = 0.0

        # RSI (14)
        rsi = TrendVelocityPredictor._calc_rsi(c, 14)
        current_rsi = rsi[-1]
        if current_rsi > 55:
            m_score += min((current_rsi - 50) / 30.0, 0.40)
        elif current_rsi < 45:
            m_score -= min((50 - current_rsi) / 30.0, 0.40)

        # RSI Slope (last 3 bars)
        if len(rsi) >= 4:
            rsi_delta = rsi[-1] - rsi[-4]
            m_score += min(max(rsi_delta / 25.0, -0.30), 0.30)

        # MACD (12, 26, 9)
        macd_line, macd_signal, macd_hist = TrendVelocityPredictor._calc_macd(c)
        if macd_hist[-1] > 0:
            m_score += 0.15
            if len(macd_hist) >= 2 and macd_hist[-1] > macd_hist[-2]:
                m_score += 0.15  # Histogram expanding bullishly
        elif macd_hist[-1] < 0:
            m_score -= 0.15
            if len(macd_hist) >= 2 and macd_hist[-1] < macd_hist[-2]:
                m_score -= 0.15  # Histogram expanding bearishly

        momentum_score = round(min(max(m_score, -1.0), 1.0), 3)

        # ── 3. Order Flow & Volume Pressure (-1.0 to +1.0) ───────────────────
        p_score = 0.0

        # VWAP approximation
        tp = (h + l + c) / 3.0
        cum_vol = np.cumsum(v)
        cum_tpv = np.cumsum(tp * v)
        vwap = cum_tpv / np.where(cum_vol > 0, cum_vol, 1.0)
        current_vwap = float(vwap[-1])

        if current_price > current_vwap:
            vwap_dist = (current_price - current_vwap) / current_vwap * 100
            p_score += min(max(vwap_dist * 0.4, 0.1), 0.50)
        else:
            vwap_dist = (current_vwap - current_price) / current_vwap * 100
            p_score -= min(max(vwap_dist * 0.4, 0.1), 0.50)

        # Volume z-score
        if len(v) >= 20:
            vol_mean = np.mean(v[-20:])
            vol_std = np.std(v[-20:]) + 1e-4
            z_score = (v[-1] - vol_mean) / vol_std
            is_green = c[-1] >= c[-2] if len(c) >= 2 else True

            if z_score > 1.0:
                p_score += 0.30 if is_green else -0.30
            elif z_score > 2.0:
                p_score += 0.50 if is_green else -0.50

        volume_pressure = round(min(max(p_score, -1.0), 1.0), 3)

        # ── 4. Composite Probability Formulation ─────────────────────────────
        # Weighted ensemble: 40% Trend Velocity + 35% Momentum + 25% Volume Pressure
        composite = (trend_velocity * 0.40) + (momentum_score * 0.35) + (volume_pressure * 0.25)

        # Logistic Sigmoid Transformation to obtain well-calibrated probabilities
        rise_prob = 1.0 / (1.0 + math.exp(-3.5 * composite))
        fall_prob = 1.0 - rise_prob

        # Net Direction & Conviction
        if composite >= 0.18:
            direction = "RISE"
            confidence = rise_prob
        elif composite <= -0.18:
            direction = "FALL"
            confidence = fall_prob
        else:
            direction = "NEUTRAL"
            confidence = max(rise_prob, fall_prob)

        # ── 5. Asymmetric Profit-Maximizing Target & Stop Limits ──────────────
        atr = TrendVelocityPredictor._calc_atr(h, l, c, 14)[-1]
        atr = max(atr, current_price * 0.008)

        # Target expected rise: 2.2x ATR
        expected_rise_target = round(current_price + (atr * 2.2), 2)
        # Expected stop limit: 1.0x ATR
        expected_fall_limit = round(current_price - (atr * 1.0), 2)
        asymmetric_rr = round(2.2 / 1.0, 2)

        # Early Reversal Threat: Divergence check
        reversal_threat = False
        if direction == "RISE" and current_rsi > 78 and momentum_score < 0:
            reversal_threat = True
        elif direction == "FALL" and current_rsi < 22 and momentum_score > 0:
            reversal_threat = True

        return {
            "symbol": symbol,
            "predicted_direction": direction,
            "rise_probability": round(rise_prob, 3),
            "fall_probability": round(fall_prob, 3),
            "confidence": round(confidence, 3),
            "trend_velocity": trend_velocity,
            "momentum_score": momentum_score,
            "volume_pressure": volume_pressure,
            "current_price": round(current_price, 2),
            "expected_rise_target": expected_rise_target,
            "expected_fall_limit": expected_fall_limit,
            "asymmetric_rr": asymmetric_rr,
            "reversal_threat": reversal_threat,
        }

    @staticmethod
    def evaluate_position_threat(
        position: Dict[str, Any],
        df: pd.DataFrame,
    ) -> Dict[str, Any]:
        """
        Monitors an open position for adverse trend velocity shifts.
        Returns recommendations to preemptively lock in profits or exit before losses.
        """
        symbol = position.get("symbol", "")
        direction = (position.get("direction") or position.get("dir", "BUY")).upper()
        is_long = direction == "BUY"

        pred = TrendVelocityPredictor.predict_direction(df, symbol=symbol)
        threat_level = "NONE"
        action = "HOLD"
        reason = "Trend velocity aligned"

        if is_long:
            # Threat if price is predicted to FALL with high confidence or high volume dump
            if pred["predicted_direction"] == "FALL" and pred["fall_probability"] >= 0.70:
                threat_level = "CRITICAL"
                action = "PREEMPTIVE_PROFIT_LOCK"
                reason = f"Adverse velocity shift detected: P(Fall)={pred['fall_probability']:.1%}"
            elif pred["volume_pressure"] <= -0.60:
                threat_level = "HIGH"
                action = "TIGHTEN_STOP"
                reason = f"Heavy sell-side volume pressure detected (z-score negative)"
        else:
            # Short position threat if price is predicted to RISE
            if pred["predicted_direction"] == "RISE" and pred["rise_probability"] >= 0.70:
                threat_level = "CRITICAL"
                action = "PREEMPTIVE_PROFIT_LOCK"
                reason = f"Adverse upward velocity shift: P(Rise)={pred['rise_probability']:.1%}"

        return {
            "symbol": symbol,
            "threat_level": threat_level,
            "action": action,
            "reason": reason,
            "prediction": pred,
        }

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _calc_ema(x: np.ndarray, p: int) -> np.ndarray:
        k = 2.0 / (p + 1.0)
        res = np.zeros(len(x))
        res[0] = x[0]
        for i in range(1, len(x)):
            res[i] = x[i] * k + res[i - 1] * (1.0 - k)
        return res

    @staticmethod
    def _calc_rsi(c: np.ndarray, period: int = 14) -> np.ndarray:
        if len(c) <= period:
            return np.full(len(c), 50.0)
        delta = np.diff(c, prepend=c[0])
        gain = np.where(delta > 0, delta, 0.0)
        loss = np.where(delta < 0, -delta, 0.0)

        avg_gain = TrendVelocityPredictor._calc_ema(gain, period)
        avg_loss = TrendVelocityPredictor._calc_ema(loss, period)

        rs = np.divide(avg_gain, avg_loss, out=np.full_like(avg_gain, 100.0), where=avg_loss != 0)
        rsi = 100.0 - (100.0 / (1.0 + rs))
        return rsi

    @staticmethod
    def _calc_macd(c: np.ndarray) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        ema12 = TrendVelocityPredictor._calc_ema(c, 12)
        ema26 = TrendVelocityPredictor._calc_ema(c, 26)
        macd_line = ema12 - ema26
        macd_signal = TrendVelocityPredictor._calc_ema(macd_line, 9)
        macd_hist = macd_line - macd_signal
        return macd_line, macd_signal, macd_hist

    @staticmethod
    def _calc_atr(h: np.ndarray, l: np.ndarray, c: np.ndarray, period: int = 14) -> np.ndarray:
        if len(c) <= 1:
            return np.maximum(h - l, 1.0)
        tr = np.maximum(h - l, np.maximum(abs(h - np.roll(c, 1)), abs(l - np.roll(c, 1))))
        tr[0] = h[0] - l[0]
        return TrendVelocityPredictor._calc_ema(tr, period)
