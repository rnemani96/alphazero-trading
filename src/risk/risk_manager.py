"""
Risk Manager

Lightweight risk gatekeeper used directly in the main loop.
(The full risk agent is GuardianAgent; this class handles simple pre-trade checks.)

FIXES:
- daily_pnl was compared against max_daily_loss (a fraction e.g. 0.02) directly,
  meaning trading would stop after losing only ₹0.02.  Now compared against the
  fractional loss of INITIAL_CAPITAL so the limit means "2% of starting capital".
- Added update_pnl() so callers can keep daily_pnl in sync.
- Added reset_daily() for EOD resets.
"""

import logging
from typing import Dict, List, Any

logger = logging.getLogger(__name__)


class RiskManager:
    """Manages trading risk — lightweight pre-trade checks."""

    def __init__(self, config: Dict):
        self.config = config
        self.max_daily_loss_pct = config.get('MAX_DAILY_LOSS_PCT', 0.02)
        self.max_position_size_pct = config.get('MAX_POSITION_SIZE_PCT', 0.05)
        self.max_positions = config.get('MAX_POSITIONS', 10)
        self.initial_capital = config.get('INITIAL_CAPITAL', 1_000_000)

        # FIX: store absolute loss threshold, not a fraction
        self.max_daily_loss_abs = self.initial_capital * self.max_daily_loss_pct

        self.daily_pnl = 0.0

    def check_trade(self, signal: Dict[str, Any], positions: List[Dict]) -> Dict[str, Any]:
        """
        Check if a trade passes basic risk limits.

        FIX: was `if self.daily_pnl < -self.max_daily_loss` which compared ₹ against
        a tiny fraction (0.02).  Now correctly compares against the absolute loss cap.
        """
        # Daily loss limit (absolute ₹)
        if self.daily_pnl < -self.max_daily_loss_abs:
            return {
                'approved': False,
                'reason': (
                    f'Daily loss limit hit: ₹{abs(self.daily_pnl):,.0f} / '
                    f'₹{self.max_daily_loss_abs:,.0f}'
                )
            }

        # Max open positions
        if len(positions) >= self.max_positions:
            return {
                'approved': False,
                'reason': f'Max positions reached ({len(positions)}/{self.max_positions})'
            }

        return {'approved': True, 'reason': 'OK'}

    def update_pnl(self, pnl_change: float):
        """
        Update running daily P&L.

        FIX: This method was missing; daily_pnl was never updated so the loss
        limit check was always comparing 0 against the threshold.
        """
        self.daily_pnl += pnl_change
        logger.debug(f"RiskManager daily P&L updated: ₹{self.daily_pnl:,.0f}")

    def reset_daily(self):
        """Reset daily counters (call at market open)."""
        self.daily_pnl = 0.0
        logger.info("RiskManager daily counters reset")
