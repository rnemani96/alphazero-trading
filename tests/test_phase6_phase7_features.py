"""
tests/test_phase6_phase7_features.py
════════════════════════════════════
Validates:
  1. Phase 6 Thompson Sampling Bandit & Experience Replay Buffer
  2. Phase 7 Interactive Trading Chatbot & Tool-calling routing
"""

import sys
import os
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from src.risk.thompson_sampling_allocator import ThompsonSamplingAllocator, get_thompson_allocator
from src.interfaces.trading_chatbot import TradingChatbot


class TestPhase6And7Features(unittest.TestCase):

    def test_thompson_sampling_posterior_update(self):
        """Test Bayesian posterior updating on wins and losses."""
        alloc = ThompsonSamplingAllocator(buffer_size=100)
        alloc.register_strategy("TREND_MOMENTUM")

        initial_alpha = alloc.priors["TREND_MOMENTUM"]["alpha"]
        initial_beta = alloc.priors["TREND_MOMENTUM"]["beta"]

        # Record a winning trade
        alloc.record_trade_outcome(
            strategy_id="TREND_MOMENTUM",
            pnl=2500.0,
            symbol="RELIANCE",
            action="BUY",
            entry_price=2500.0,
            exit_price=2550.0,
        )

        self.assertEqual(alloc.priors["TREND_MOMENTUM"]["alpha"], initial_alpha + 1.0)
        self.assertEqual(alloc.priors["TREND_MOMENTUM"]["beta"], initial_beta)
        self.assertEqual(alloc.priors["TREND_MOMENTUM"]["wins"], 1)

        # Record a losing trade
        alloc.record_trade_outcome(
            strategy_id="TREND_MOMENTUM",
            pnl=-1000.0,
            symbol="RELIANCE",
            action="BUY",
            entry_price=2550.0,
            exit_price=2530.0,
        )

        self.assertEqual(alloc.priors["TREND_MOMENTUM"]["beta"], initial_beta + 1.0)
        self.assertEqual(alloc.priors["TREND_MOMENTUM"]["losses"], 1)

    def test_experience_replay_buffer(self):
        """Test replay buffer sampling for online learning without catastrophic forgetting."""
        alloc = ThompsonSamplingAllocator(buffer_size=50)
        for i in range(10):
            alloc.record_trade_outcome(
                strategy_id=f"STRAT_{i%3}",
                pnl=500.0 if i % 2 == 0 else -300.0,
                symbol=f"SYM_{i}",
            )

        self.assertEqual(len(alloc.replay_buffer), 10)
        batch = alloc.sample_replay_batch(batch_size=4)
        self.assertEqual(len(batch), 4)
        self.assertIn("strategy_id", batch[0])
        self.assertIn("pnl", batch[0])

    def test_trading_chatbot_tool_routing(self):
        """Test that chatbot detects intent and executes appropriate tools."""
        chatbot = TradingChatbot()

        # Test portfolio query
        p_res = chatbot.chat("Show me my portfolio positions and pnl")
        self.assertEqual(p_res.get("tool_executed"), "portfolio_status")
        self.assertIn("portfolio", p_res.get("tool_data", {}))

        # Test market regime query
        m_res = chatbot.chat("What is the current market regime and vix?")
        self.assertEqual(m_res.get("tool_executed"), "market_regime")
        self.assertIn("market", m_res.get("tool_data", {}))

        # Test symbol analysis query
        s_res = chatbot.chat("Analyze RELIANCE")
        self.assertEqual(s_res.get("tool_executed"), "analyze_symbol")
        self.assertIn("analysis", s_res.get("tool_data", {}))

        # Test trade execution intent
        t_res = chatbot.chat("Buy 5 shares of TATASTEEL")
        self.assertEqual(t_res.get("tool_executed"), "execute_trade")
        self.assertIn("execution", t_res.get("tool_data", {}))


if __name__ == "__main__":
    unittest.main()
