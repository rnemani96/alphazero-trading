"""
AlphaZero Capital — Risk Manager
src/risk/risk_manager.py

Lightweight pre-trade risk gatekeeper used directly in the main loop.

Fixed:
  - Constructor now accepts (event_bus, config) matching main.py call
  - Added get_available_capital()
  - Added get_current_value()
  - Added kill_switch_active attribute
  - update_pnl() accepts optional second arg (main.py passes two args)
  - Daily loss compared against absolute INR threshold, not raw fraction
"""

import logging
from typing import Dict, List, Any, Optional

logger = logging.getLogger(__name__)


class RiskManager:

    def __init__(self, event_bus=None, config: Dict = None):
        # Accept (event_bus, config) OR legacy (config,) / (config_dict,)
        if config is None and isinstance(event_bus, dict):
            config = event_bus
            event_bus = None

        self.event_bus = event_bus
        self.config    = config or {}

        self.max_daily_loss_pct    = self.config.get('MAX_DAILY_LOSS_PCT',    0.02)
        self.max_position_size_pct = self.config.get('MAX_POSITION_SIZE_PCT', 0.05)
        self.max_positions         = self.config.get('MAX_POSITIONS',         10)
        self.initial_capital       = self.config.get('INITIAL_CAPITAL',       1_000_000)
        self.max_trades_per_day    = self.config.get('MAX_TRADES_PER_DAY',    20)

        # Absolute INR loss limit
        self.max_daily_loss_abs = self.initial_capital * self.max_daily_loss_pct

        self.daily_pnl          = 0.0
        self.trades_today       = 0
        self.kill_switch_active = False

    # ── Core check ────────────────────────────────────────────────────────────

    def check_trade(self, signal: Dict[str, Any],
                    positions: List[Dict]) -> Dict[str, Any]:
        if self.kill_switch_active:
            return {'approved': False, 'reason': 'Kill switch active'}

        if self.daily_pnl < -self.max_daily_loss_abs:
            self.kill_switch_active = True
            logger.warning(f"Kill switch: daily loss INR{abs(self.daily_pnl):,.0f} "
                           f"exceeded INR{self.max_daily_loss_abs:,.0f}")
            return {'approved': False,
                    'reason': f'Daily loss limit INR{self.max_daily_loss_abs:,.0f} hit'}

        if len(positions) >= self.max_positions:
            return {'approved': False,
                    'reason': f'Max positions {self.max_positions} reached'}

        if self.trades_today >= self.max_trades_per_day:
            return {'approved': False,
                    'reason': f'Max {self.max_trades_per_day} trades/day reached'}

        return {'approved': True, 'reason': 'OK'}

    # ── Capital helpers ───────────────────────────────────────────────────────

    def get_available_capital(self) -> float:
        """Capital available for new trades (95% of current value)."""
        current = self.initial_capital + self.daily_pnl
        return max(0.0, current * 0.95)

    def get_current_value(self) -> float:
        """Current portfolio value."""
        return self.initial_capital + self.daily_pnl

    def get_position_size(self, price: float,
                          capital: Optional[float] = None) -> int:
        """Max quantity for one position."""
        available = capital or self.get_available_capital()
        max_value = available * self.max_position_size_pct
        if price <= 0:
            return 0
        return max(1, int(max_value / price))

    # ── State updates ─────────────────────────────────────────────────────────

    def update_pnl(self, pnl_change: float, is_win: bool = False):
        """
        Update daily P&L.
        Accepts optional second positional arg so callers can do
        update_pnl(amount, True/False) without error.
        """
        self.daily_pnl += pnl_change
        if pnl_change != 0:
            self.trades_today += 1

        if (self.daily_pnl < -self.max_daily_loss_abs
                and not self.kill_switch_active):
            self.kill_switch_active = True
            logger.warning("Kill switch activated — daily loss limit reached")

    def record_trade(self):
        self.trades_today += 1

    def reset_daily(self):
        self.daily_pnl          = 0.0
        self.trades_today       = 0
        self.kill_switch_active = False
        logger.info("RiskManager daily counters reset")
