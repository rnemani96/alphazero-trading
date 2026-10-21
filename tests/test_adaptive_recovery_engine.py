"""
tests/test_adaptive_recovery_engine.py
══════════════════════════════════════
Comprehensive test suite for AdaptiveProfitLossRecoveryEngine:
1. Self-adjusting threshold calibration across market regimes and VIX
2. Zero-Loss cost-covered breakeven ratchet (including Indian market charges)
3. Profit locking ladder (+1R, +2R, +3R)
4. Loss deficit calculation and automated recovery hurdle planning
5. Candidate signal gating based on recovery mode
6. Multi-stage deficit recovery and profit surplus restoration
7. State persistence and reload
"""

import os
import sys
import tempfile
import unittest

# Ensure repo root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.risk.adaptive_recovery_engine import (
    AdaptiveProfitLossRecoveryEngine,
    AdaptiveThresholds,
)


class TestAdaptiveProfitLossRecoveryEngine(unittest.TestCase):

    def setUp(self):
        self.engine = AdaptiveProfitLossRecoveryEngine(initial_capital=1_000_000.0)
        self.engine.unrecovered_deficit = 0.0
        self.engine.loss_ledger = []
        self.engine.in_recovery_mode = False
        self.engine.total_recoveries_completed = 0
        self.engine.total_recovered_pnl = 0.0

    def test_01_self_adjusting_thresholds_trending(self):
        """Trending bull regime should set relaxed confidence and high reward multiples."""
        th = self.engine.update_market_context(regime="TRENDING", vix=13.5, win_rate_20=0.65)
        self.assertEqual(th.mode_label, "BALANCED_GROWTH")
        self.assertLessEqual(th.min_confidence, 0.55)
        self.assertEqual(th.min_agent_agreement, 1)
        self.assertGreaterEqual(th.trail_atr_multiplier, 1.5)

    def test_02_self_adjusting_thresholds_volatile_vix(self):
        """Volatile regime with VIX > 25 should automatically tighten confidence and risk."""
        th = self.engine.update_market_context(regime="VOLATILE", vix=29.0, win_rate_20=0.45)
        self.assertGreaterEqual(th.min_confidence, 0.75)
        self.assertGreaterEqual(th.min_agent_agreement, 2)
        self.assertLessEqual(th.max_risk_pct_per_trade, 0.015)
        self.assertGreaterEqual(th.min_rr_ratio, 2.2)

    def test_03_zero_loss_breakeven_ratchet(self):
        """When position gains enough to cover roundtrip charges + cushion, ratchet to Breakeven."""
        position = {
            "symbol": "TCS",
            "entry_price": 3500.0,
            "quantity": 20,
            "stop_loss": 3430.0,  # Initial 2% risk stop
            "target": 3710.0,
            "direction": "BUY",
            "breakeven_done": False,
        }
        # Price is up 1.0% (3535.0) -> exceeds breakeven_trigger_pct (0.75%)
        eval_res = self.engine.evaluate_position_protection(
            position=position,
            current_price=3535.0,
            atr=50.0,
        )
        self.assertEqual(eval_res["action"], "MOVE_TO_BREAKEVEN")
        self.assertTrue(eval_res["is_cost_covered"])
        # Stop loss must be higher than entry price (entry + roundtrip charges + buffer)
        self.assertGreater(eval_res["new_sl"], 3500.0)

    def test_04_profit_locking_ladder(self):
        """At +2R gain, stop loss must lock in > 1R profit."""
        position = {
            "symbol": "INFY",
            "entry_price": 1500.0,
            "quantity": 50,
            "stop_loss": 1470.0,  # 30 pt initial risk (1R)
            "target": 1650.0,
            "direction": "BUY",
            "breakeven_done": True,
        }
        # Price is at 1565 (+65 pts = +2.16R gain)
        eval_res = self.engine.evaluate_position_protection(
            position=position,
            current_price=1565.0,
            atr=25.0,
        )
        self.assertEqual(eval_res["action"], "TRAIL_PROFIT")
        # Should lock at least +1.2R (1500 + 36 = 1536)
        self.assertGreaterEqual(eval_res["new_sl"], 1536.0)
        self.assertGreater(eval_res["locked_pnl"], 1500.0)

    def test_05_loss_registration_and_recovery_plan(self):
        """A loss must trigger RECOVERY_MODE, record deficit, and generate mathematical plan."""
        loss_trade = {
            "symbol": "RELIANCE",
            "realised_pnl": -4500.0,
            "charges": 80.0,
            "strategy": "MOMENTUM_BREAKOUT",
        }
        res = self.engine.register_trade_outcome(loss_trade)
        self.assertEqual(res["status"], "DEFICIT_ADDED")
        self.assertTrue(self.engine.in_recovery_mode)
        self.assertGreaterEqual(self.engine.unrecovered_deficit, 4500.0)

        plan = res["recovery_plan"]
        self.assertTrue(plan["in_recovery"])
        self.assertGreater(plan["target_recovery_amount"], 4500.0)
        self.assertGreaterEqual(plan["required_rr_ratio"], 2.5)

        # Thresholds must now be in recovery mode
        self.assertEqual(self.engine.thresholds.mode_label, "RECOVERY_HURDLE")
        self.assertGreaterEqual(self.engine.thresholds.min_confidence, 0.70)

    def test_06_candidate_signal_gating_in_recovery(self):
        """In recovery mode, mediocre signals must be rejected; Grade-A+ signals approved."""
        # Force recovery mode with deficit
        self.engine.register_trade_outcome({"symbol": "TEST", "realised_pnl": -3000.0, "charges": 50.0})

        # Mediocre signal (confidence 0.58, R:R 1.8) -> REJECTED
        mediocre = {"symbol": "SBIN", "confidence": 0.58, "rr_ratio": 1.8, "agent_agreement": 1}
        ok, reason = self.engine.validate_candidate_signal(mediocre)
        self.assertFalse(ok)
        self.assertIn("adaptive threshold", reason)

        # Grade-A+ signal (confidence 0.82, R:R 3.0, agreement 2) -> APPROVED
        prime_setup = {"symbol": "HDFCBANK", "confidence": 0.82, "rr_ratio": 3.0, "agent_agreement": 2}
        ok2, reason2 = self.engine.validate_candidate_signal(prime_setup)
        self.assertTrue(ok2)
        self.assertEqual(reason2, "APPROVED_BY_ADAPTIVE_ENGINE")

    def test_07_recovery_completion_and_profit_surplus(self):
        """Profitable recovery trade must erase deficit, achieve surplus, and reset mode."""
        # 1. Register loss of Rs 5,000
        self.engine.register_trade_outcome({"symbol": "ICICIBANK", "realised_pnl": -5000.0, "charges": 50.0})
        self.assertTrue(self.engine.in_recovery_mode)
        self.assertAlmostEqual(self.engine.unrecovered_deficit, 5000.0, delta=1.0)

        # 2. Winning trade of Rs 7,500 (covers 5,000 deficit + 2,500 surplus profit)
        win_trade = {
            "symbol": "BAJFINANCE",
            "realised_pnl": 7500.0,
            "charges": 60.0,
            "strategy": "ALPHA_RECOVERY",
        }
        res = self.engine.register_trade_outcome(win_trade)
        self.assertEqual(res["status"], "RECOVERY_COMPLETE")
        self.assertFalse(self.engine.in_recovery_mode)
        self.assertEqual(self.engine.unrecovered_deficit, 0.0)
        self.assertGreaterEqual(res["surplus_profit"], 2400.0)
        self.assertEqual(self.engine.total_recoveries_completed, 1)

        # Thresholds should be back to standard balanced growth
        self.assertEqual(self.engine.thresholds.mode_label, "BALANCED_GROWTH")


if __name__ == "__main__":
    unittest.main()
