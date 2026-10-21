"""
tests/test_risk_math_and_direction.py
════════════════════════════════════
Validates:
  1. Direction-aware SL & Target for both BUY and SELL (short) trades.
  2. get_minimum_viable_quantity works for both BUY and SELL trades.
  3. ActivePortfolio can_add_position and get_progress work without KeyError on compound keys.
  4. HERMES (NewsSentimentAgent) and SHADOW_LSTM (LSTMAgent) load and execute without PyTorch dependency crashes.
"""

import sys
import os
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.risk.position_sizer import optimal_size, PositionSizer
from src.risk.charge_calculator import get_minimum_viable_quantity, calculate_charges
from src.risk.active_portfolio import ActivePortfolio, PositionStatus


class TestRiskMathAndDirection(unittest.TestCase):

    def test_direction_aware_sizing(self):
        """Verify BUY has SL below entry, Target above entry; SELL has SL above entry, Target below entry."""
        capital = 1000000.0
        price = 1000.0
        atr = 20.0

        # BUY Trade
        buy_res = optimal_size(capital, price, atr, action="BUY")
        self.assertLess(buy_res["stop_loss"], price, "BUY stop loss must be below entry price")
        self.assertGreater(buy_res["target"], price, "BUY target must be above entry price")

        # SELL Trade
        sell_res = optimal_size(capital, price, atr, action="SELL")
        self.assertGreater(sell_res["stop_loss"], price, "SELL stop loss must be above entry price")
        self.assertLess(sell_res["target"], price, "SELL target must be below entry price")

    def test_short_trade_viability_calculation(self):
        """Verify get_minimum_viable_quantity correctly measures viability for short trades."""
        entry = 1000.0
        target_buy = 1050.0   # +5% Long
        target_sell = 950.0   # -5% Short

        qty_buy = get_minimum_viable_quantity(entry, target_buy, is_intraday=False)
        qty_sell = get_minimum_viable_quantity(entry, target_sell, is_intraday=False)

        self.assertGreater(qty_buy, 0)
        self.assertGreater(qty_sell, 0)

        # Check charges for sell trade
        res_sell = calculate_charges(qty_sell, buy_price=target_sell, sell_price=entry, is_intraday=False)
        self.assertGreater(res_sell["net_pnl"], 0, "Net PnL should be positive for profitable short")

    def test_active_portfolio_compound_key_handling(self):
        """Verify can_add_position and get_progress handle compound 'SYMBOL:TYPE' keys without KeyError."""
        test_file = os.path.join(os.path.dirname(__file__), "test_temp_portfolio.json")
        if os.path.exists(test_file):
            os.remove(test_file)

        ap = ActivePortfolio(path=test_file, max_positions=5)
        # Add a position
        pos = ap.open_position("TCS", 3500.0, 10, target=3700.0, stop_loss=3400.0, trade_type="SWING")
        self.assertEqual(pos["status"], PositionStatus.OPEN)

        # Attempt to add same position again - should safely return False without KeyError
        can_add, reason = ap.can_add_position("TCS", trade_type="SWING")
        self.assertFalse(can_add)
        self.assertIn("already invested", reason)

        # Test get_progress
        prog = ap.get_progress("TCS")
        self.assertIsNotNone(prog)
        self.assertEqual(prog["symbol"], "TCS")
        self.assertIn("pct_to_target", prog)

        # Cleanup
        if os.path.exists(test_file):
            os.remove(test_file)

    def test_shadow_lstm_and_hermes_fallbacks(self):
        """Verify that LSTMAgent and NewsSentimentAgent load and predict cleanly."""
        from src.agents.lstm_agent import LSTMAgent
        from src.agents.news_sentiment_agent import NewsSentimentAgent
        import pandas as pd
        import numpy as np

        eb = None
        cfg = {}

        lstm = LSTMAgent(eb, cfg)
        self.assertTrue(lstm.is_active)

        # Test LSTM predict with synthetic dataframe
        dates = pd.date_range("2026-01-01", periods=40, freq="15min")
        df = pd.DataFrame({
            "open": np.linspace(100, 110, 40),
            "high": np.linspace(101, 112, 40),
            "low": np.linspace(99, 109, 40),
            "close": np.linspace(100.5, 111.5, 40),
            "volume": np.full(40, 5000),
        }, index=dates)

        pred = lstm.predict("TEST_SYM", df)
        self.assertIn("confidence", pred)
        self.assertIn("action", pred)
        self.assertGreater(pred["confidence"], 0.0)

        # Test HERMES sentiment processor
        from src.data.sentiment.processor import SentimentProcessor
        proc = SentimentProcessor()
        test_headlines = [
            {"headline": "TCS reports record profit surge in cloud contracts", "symbol": "TCS"},
            {"headline": "Weak performance and drop in sales leads to downgrade", "symbol": "INFY"}
        ]
        scored = proc.process_batch(test_headlines)
        self.assertEqual(len(scored), 2)
        self.assertIn("sentiment_score", scored[0])
        self.assertGreater(scored[0]["sentiment_score"], 0.0, "Positive headline should have positive score")
        self.assertLess(scored[1]["sentiment_score"], 0.0, "Negative headline should have negative score")


if __name__ == "__main__":
    unittest.main()
