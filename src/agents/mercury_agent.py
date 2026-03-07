"""
MERCURY Agent - Trade Execution

Single execution gate - all trades go through here.
Monitors execution quality and manages order placement.

FIXES:
- Removed markdown header block (lines 1-5 + closing ```) that caused SyntaxError
- Fixed signal key: signal dict uses 'signal' key (BUY/SELL), not 'action'
- Added close_position() wrapper method that was missing
"""

import logging
from typing import Dict, List, Any, Optional
from datetime import datetime

from ..event_bus.event_bus import BaseAgent, EventType

logger = logging.getLogger(__name__)


class MercuryAgent(BaseAgent):
    """
    MERCURY - Execution Quality Agent

    Responsibilities:
    - Execute trades via OpenAlgo
    - Monitor slippage and spread
    - Track fill quality
    - Order management
    - Execution reporting

    KPI: Slippage < 0.15% per trade
    """

    def __init__(self, event_bus, config, executor):
        super().__init__(event_bus=event_bus, config=config, name="MERCURY")

        self.executor = executor  # OpenAlgoExecutor or PaperExecutor

        # Execution tracking
        self.total_trades = 0
        self.total_slippage = 0.0
        self.failed_trades = 0

        # Limits
        self.max_slippage_pct = config.get('MAX_SLIPPAGE_PCT', 0.003)
        self.max_spread_pct = config.get('MAX_SPREAD_PCT', 0.002)

        logger.info("MERCURY Agent initialized - Execution ready")

    def execute_trade(
        self,
        signal: Dict[str, Any],
        position_size: float = 0.0
    ) -> Dict[str, Any]:
        """
        Execute a trade.

        Args:
            signal: Trading signal dict; expects 'symbol' and 'signal' (BUY/SELL) keys.
            position_size: Position size in rupees (optional; used to calculate qty).

        Returns:
            Execution result with fill details.

        FIXES:
        - Was reading signal['action'] which didn't match the 'signal' key used by TITAN/main.py
        """
        symbol = signal['symbol']
        # FIX: key is 'signal' (BUY/SELL), not 'action'
        action = signal.get('signal') or signal.get('action', 'BUY')

        logger.info(f"MERCURY executing: {action} {symbol} ₹{position_size:,.0f}")

        try:
            result = self.executor.execute_trade({
                'symbol': symbol,
                'signal': action,
                'action': action,
                'quantity': self._calculate_quantity(symbol, position_size),
                'signal_detail': signal
            })

            if result.get('success'):
                slippage = self._calculate_slippage(
                    signal.get('expected_price', 0),
                    result.get('fill_price', 0)
                )

                self.total_trades += 1
                self.total_slippage += slippage

                if slippage > self.max_slippage_pct:
                    logger.warning(f"High slippage: {slippage:.2%} for {symbol}")

                self.publish_event(
                    EventType.TRADE_EXECUTED,
                    {
                        'symbol': symbol,
                        'action': action,
                        'quantity': result.get('quantity'),
                        'fill_price': result.get('fill_price'),
                        'slippage': slippage,
                        'timestamp': datetime.now().isoformat()
                    }
                )

                logger.info(
                    f"✅ MERCURY executed: {symbol} @ ₹{result.get('fill_price')} "
                    f"(slippage: {slippage:.2%})"
                )
                return {
                    'success': True,
                    'fill_price': result.get('fill_price'),
                    'quantity': result.get('quantity'),
                    'slippage': slippage,
                    'stop_loss': result.get('stop_loss')
                }

            else:
                self.failed_trades += 1
                logger.error(f"❌ Execution failed: {symbol} - {result.get('error')}")
                return {'success': False, 'error': result.get('error')}

        except Exception as e:
            self.failed_trades += 1
            logger.error(f"❌ Execution error: {e}", exc_info=True)
            return {'success': False, 'error': str(e)}

    def close_position(self, position: Dict[str, Any]) -> Dict[str, Any]:
        """
        Close an open position.

        FIXES: Method was missing from this class but called elsewhere.
        """
        try:
            result = self.executor.close_position(position)
            if result.get('success'):
                self.publish_event(
                    EventType.POSITION_CLOSED,
                    {
                        'symbol': position['symbol'],
                        'pnl': result.get('pnl', 0),
                        'timestamp': datetime.now().isoformat()
                    }
                )
            return result
        except Exception as e:
            logger.error(f"❌ Close position error: {e}", exc_info=True)
            return {'success': False, 'error': str(e)}

    def _calculate_quantity(self, symbol: str, position_size: float) -> int:
        """Calculate quantity based on position size (uses placeholder price)."""
        # In production: fetch live LTP from data feed
        price = 2450  # Placeholder
        quantity = int(position_size / price) if price > 0 else 1
        return max(quantity, 1)

    def _calculate_slippage(self, expected_price: float, fill_price: float) -> float:
        """Calculate slippage percentage."""
        if expected_price == 0 or fill_price == 0:
            return 0.0
        return abs(fill_price - expected_price) / expected_price

    def get_stats(self) -> Dict[str, Any]:
        """Get MERCURY statistics."""
        avg_slippage = (
            self.total_slippage / self.total_trades
        ) if self.total_trades > 0 else 0.0

        return {
            'name': self.name,
            'active': self.is_active,
            'total_trades': self.total_trades,
            'failed_trades': self.failed_trades,
            'avg_slippage': avg_slippage,
            'kpi': 'Slippage < 0.15%'
        }
