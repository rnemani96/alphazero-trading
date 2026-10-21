"""
tests/test_trend_velocity_predictor.py
══════════════════════════════════════
Tests for TrendVelocityPredictor:
1. Bullish series yields RISE direction with high rise probability
2. Bearish series yields FALL direction with high fall probability
3. Early adverse threat detection on open positions
4. Target and stop calculations maintain asymmetric risk/reward
"""

import os
import sys
import unittest
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.data.trend_velocity_predictor import TrendVelocityPredictor


class TestTrendVelocityPredictor(unittest.TestCase):

    def test_01_predict_rise(self):
        """Monotonically rising prices with volume surge should predict RISE with high confidence."""
        n = 50
        base = 100.0
        # Create steady uptrend
        prices = [base + i * 1.5 + np.sin(i) * 0.5 for i in range(n)]
        df = pd.DataFrame({
            "open": [p - 0.5 for p in prices],
            "high": [p + 1.0 for p in prices],
            "low": [p - 1.0 for p in prices],
            "close": prices,
            "volume": [1000 + i * 50 for i in range(n)],
        })

        pred = TrendVelocityPredictor.predict_direction(df, symbol="BULL_STOCK")
        self.assertEqual(pred["predicted_direction"], "RISE")
        self.assertGreaterEqual(pred["rise_probability"], 0.70)
        self.assertGreater(pred["expected_rise_target"], pred["current_price"])
        self.assertLess(pred["expected_fall_limit"], pred["current_price"])
        self.assertGreaterEqual(pred["asymmetric_rr"], 2.0)

    def test_02_predict_fall(self):
        """Monotonically falling prices should predict FALL with high fall probability."""
        n = 50
        base = 200.0
        # Create steady downtrend
        prices = [base - i * 1.5 - np.sin(i) * 0.5 for i in range(n)]
        df = pd.DataFrame({
            "open": [p + 0.5 for p in prices],
            "high": [p + 1.0 for p in prices],
            "low": [p - 1.0 for p in prices],
            "close": prices,
            "volume": [1000 + i * 50 for i in range(n)],
        })

        pred = TrendVelocityPredictor.predict_direction(df, symbol="BEAR_STOCK")
        self.assertEqual(pred["predicted_direction"], "FALL")
        self.assertGreaterEqual(pred["fall_probability"], 0.70)
        self.assertLess(pred["trend_velocity"], 0.0)

    def test_03_evaluate_position_threat(self):
        """A LONG position encountering a strong downward trend should trigger a CRITICAL threat."""
        n = 40
        # Start high and crash down
        prices = [150.0 - (i * 2.0) for i in range(n)]
        df = pd.DataFrame({
            "open": [p + 0.5 for p in prices],
            "high": [p + 1.0 for p in prices],
            "low": [p - 1.0 for p in prices],
            "close": prices,
            "volume": [2000] * n,
        })
        position = {
            "symbol": "DANGER_STOCK",
            "direction": "BUY",
            "entry_price": 145.0,
            "stop_loss": 130.0,
        }
        threat = TrendVelocityPredictor.evaluate_position_threat(position, df)
        self.assertEqual(threat["threat_level"], "CRITICAL")
        self.assertEqual(threat["action"], "PREEMPTIVE_PROFIT_LOCK")
        self.assertIn("Adverse velocity shift", threat["reason"])


if __name__ == "__main__":
    unittest.main()
