"""
GUARDIAN Agent - Risk Officer

Enforces all risk limits and makes kill/approve decisions.
The system's safety net - cannot be overridden by AI.

FIXES:
- _get_sector() now imports and uses sectors.py (SECTORS dict) instead of a
  hard-coded four-stock dict.
- check_trade() signature note: this class takes (signal, current_capital, positions);
  the lightweight RiskManager in risk_manager.py takes (signal, positions) only.
  Both coexist — main.py uses RiskManager; GuardianAgent is used via event bus / direct call.
"""

import logging
from typing import Dict, List, Any, Optional
from datetime import datetime

from ..event_bus.event_bus import BaseAgent, EventType

logger = logging.getLogger(__name__)


# FIX: Build a reverse lookup {symbol → sector} from sectors.py at import time.
# This avoids a hard-coded 4-stock dict.
try:
    from config.sectors import SECTORS as _SECTORS
except ImportError:
    try:
        from config.sectors import SECTORS as _SECTORS
    except ImportError:
        _SECTORS = {}

_SYMBOL_TO_SECTOR: Dict[str, str] = {}
for _sector, _stocks in _SECTORS.items():
    for _sym in _stocks:
        _SYMBOL_TO_SECTOR[_sym] = _sector


class GuardianAgent(BaseAgent):
    """
    GUARDIAN - Risk Officer Agent

    Responsibilities:
    - Enforce daily loss limits
    - Check position sizing
    - Kill switch management
    - Overtrading prevention
    - Volatility shutdown

    KPI: Max drawdown never exceeds 8%
    """

    def __init__(self, event_bus, config):
        super().__init__(event_bus=event_bus, config=config, name="GUARDIAN")

        # Risk limits (HARD RULES - cannot be overridden)
        self.max_daily_loss_pct = config.get('MAX_DAILY_LOSS_PCT', 0.02)
        self.max_position_size_pct = config.get('MAX_POSITION_SIZE_PCT', 0.05)
        self.max_sector_exposure_pct = config.get('MAX_SECTOR_EXPOSURE_PCT', 0.30)
        self.max_positions = config.get('MAX_POSITIONS', 10)
        self.max_trades_per_day = config.get('MAX_TRADES_PER_DAY', 20)
        self.consecutive_loss_limit = config.get('CONSECUTIVE_LOSS_LIMIT', 3)
        self.initial_capital = config.get('INITIAL_CAPITAL', 1_000_000)

        # State tracking
        self.daily_pnl = 0.0
        self.current_positions: List[Dict] = []
        self.trades_today = 0
        self.consecutive_losses = 0
        self.kill_switch_active = False
        self.trade_decisions = 0

        self.last_reset_date = datetime.now().date()

        logger.info("GUARDIAN Agent initialized - Risk limits active")

    def check_trade(
        self,
        signal: Dict[str, Any],
        current_capital: float,
        positions: List[Dict]
    ) -> Dict[str, Any]:
        """
        Check if trade passes all risk limits.

        Args:
            signal: Trading signal to check
            current_capital: Available capital
            positions: Current open positions

        Returns:
            {'approved': bool, 'reason': str, 'position_size': float}
        """
        self.trade_decisions += 1
        self._check_daily_reset()

        if self.kill_switch_active:
            return {'approved': False, 'reason': 'KILL_SWITCH_ACTIVE', 'position_size': 0}

        # Daily loss limit (compare P&L as % of initial capital)
        daily_loss_pct = abs(self.daily_pnl) / self.initial_capital if self.initial_capital > 0 else 0
        if self.daily_pnl < 0 and daily_loss_pct >= self.max_daily_loss_pct:
            self._activate_kill_switch(f"Daily loss limit hit: {daily_loss_pct:.1%}")
            return {
                'approved': False,
                'reason': f'DAILY_LOSS_LIMIT ({daily_loss_pct:.1%})',
                'position_size': 0
            }

        if len(positions) >= self.max_positions:
            return {
                'approved': False,
                'reason': f'MAX_POSITIONS_REACHED ({len(positions)}/{self.max_positions})',
                'position_size': 0
            }

        if self.trades_today >= self.max_trades_per_day:
            return {
                'approved': False,
                'reason': f'MAX_TRADES_TODAY ({self.trades_today}/{self.max_trades_per_day})',
                'position_size': 0
            }

        if self.consecutive_losses >= self.consecutive_loss_limit:
            return {
                'approved': False,
                'reason': f'CONSECUTIVE_LOSSES ({self.consecutive_losses} in a row)',
                'position_size': 0
            }

        # Position sizing
        position_size = min(
            current_capital * self.max_position_size_pct,
            signal.get('suggested_size', current_capital * 0.05)
        )

        # Sector exposure
        symbol = signal.get('symbol', '')
        sector = self._get_sector(symbol)
        sector_exposure = self._calculate_sector_exposure(positions, sector)

        if sector_exposure + position_size > current_capital * self.max_sector_exposure_pct:
            return {
                'approved': False,
                'reason': f'SECTOR_EXPOSURE_LIMIT ({sector})',
                'position_size': 0
            }

        self.trades_today += 1

        self.publish_event(
            EventType.RISK_ALERT,
            {
                'action': 'TRADE_APPROVED',
                'symbol': symbol,
                'position_size': position_size,
                'checks_passed': 7
            }
        )

        logger.info(f"GUARDIAN approved trade: {symbol} (₹{position_size:,.0f})")
        return {'approved': True, 'reason': 'ALL_CHECKS_PASSED', 'position_size': position_size}

    def update_pnl(self, pnl_change: float, is_loss: bool):
        """Update daily PnL and consecutive loss tracking."""
        self.daily_pnl += pnl_change
        if is_loss:
            self.consecutive_losses += 1
        else:
            self.consecutive_losses = 0
        logger.info(f"GUARDIAN PnL update: ₹{pnl_change:,.0f} (Total: ₹{self.daily_pnl:,.0f})")

    def _activate_kill_switch(self, reason: str):
        """Activate emergency kill switch."""
        self.kill_switch_active = True
        self.publish_event(
            EventType.RISK_ALERT,
            {
                'action': 'KILL_SWITCH_ACTIVATED',
                'reason': reason,
                'timestamp': datetime.now().isoformat()
            }
        )
        logger.critical(f"🚨 KILL SWITCH ACTIVATED: {reason}")

    def reset_kill_switch(self):
        """Manually reset kill switch (requires human approval)."""
        self.kill_switch_active = False
        logger.warning("⚠️ Kill switch manually reset")

    def _check_daily_reset(self):
        """Reset daily counters at market open."""
        today = datetime.now().date()
        if today > self.last_reset_date:
            self.daily_pnl = 0.0
            self.trades_today = 0
            self.consecutive_losses = 0
            self.last_reset_date = today
            logger.info("GUARDIAN daily reset complete")

    def _get_sector(self, symbol: str) -> str:
        """
        Get sector for symbol using sectors.py SECTORS dict.

        FIX: Previously only mapped 4 hard-coded symbols; now uses the full
        SECTORS dictionary loaded at module level.
        """
        return _SYMBOL_TO_SECTOR.get(symbol, 'OTHER')

    def _calculate_sector_exposure(self, positions: List[Dict], sector: str) -> float:
        """Calculate total capital exposure in a given sector."""
        return sum(
            pos.get('value', pos.get('entry_price', 0) * pos.get('quantity', 0))
            for pos in positions
            if self._get_sector(pos['symbol']) == sector
        )

    def get_stats(self) -> Dict[str, Any]:
        """Get GUARDIAN statistics."""
        return {
            'name': self.name,
            'active': self.is_active,
            'kill_switch': self.kill_switch_active,
            'daily_pnl': self.daily_pnl,
            'trades_today': self.trades_today,
            'consecutive_losses': self.consecutive_losses,
            'trade_decisions': self.trade_decisions,
            'kpi': 'Max drawdown < 8%'
        }
