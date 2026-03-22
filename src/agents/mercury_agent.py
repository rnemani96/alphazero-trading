"""
MERCURY Agent - Trade Execution
src/agents/mercury_agent.py

FIXES:
  1. _calculate_quantity: was using hardcoded price=2450 — now uses real LTP from signal
  2. execute_trade: now passes price/atr/stop fields to executor so PaperExecutor
     can fill at the real market price instead of 2450.50
  3. update_prices(): new method — called by main loop each iteration to push
     fresh prices into PaperExecutor for P&L and stop/target monitoring
"""

import logging
from typing import Dict, Any, Optional
from datetime import datetime

try:
    from src.event_bus.event_bus import BaseAgent, EventType
except ImportError:
    try:
        from ..event_bus.event_bus import BaseAgent, EventType
    except ImportError:
        # Fallback for static analysis tools
        class BaseAgent:
            def __init__(self, event_bus=None, config=None, name=""):
                self.event_bus = event_bus; self.config = config or {}; self.name = name
                self.is_active = True; self.last_activity = "Initialised"
            def publish_event(self, *a, **k): pass
            def subscribe(self, *a, **k): pass
        class EventType:
            SIGNAL_GENERATED = "signal_generated"
            POSITION_CLOSED = "position_closed"
            TRADE_EXECUTED = "trade_executed"

logger = logging.getLogger(__name__)


class MercuryAgent(BaseAgent):
    """
    MERCURY - Execution Quality Agent
    Single execution gate — all trades go through here.
    KPI: Slippage < 0.15% per trade
    """

    def __init__(self, event_bus, config, executor):
        super().__init__(event_bus=event_bus, config=config, name="MERCURY")
        self.executor = executor
        self.total_trades   = 0
        self.total_slippage = 0.0
        self.failed_trades  = 0
        self.max_slippage_pct = config.get('MAX_SLIPPAGE_PCT', 0.003)
        logger.info("MERCURY Agent initialized - Execution ready")

    # ── public API ────────────────────────────────────────────────────────────

    def execute_trade(self, signal: Dict[str, Any], position_size: float = 0.0) -> Dict[str, Any]:
        """
        Execute a trade.
        signal: must have 'symbol' and 'signal'/'action' (BUY/SELL).
        position_size: INR size — used to calculate quantity.
        """
        symbol = signal['symbol']
        action = (signal.get('signal') or signal.get('action', 'BUY')).upper()

        # Get real LTP — try signal fields in order of preference
        ltp = (
            signal.get('price') or
            signal.get('ltp') or
            signal.get('current_price') or
            signal.get('entry_price') or
            0.0
        )

        # Calculate realistic quantity from position_size and real price
        qty = self._calculate_quantity_from_price(position_size, ltp)

        logger.info(f"MERCURY executing: {action} {symbol} ×{qty} ₹{position_size:,.0f} LTP=₹{ltp:.2f}")

        try:
            result = self.executor.execute_trade({
                'symbol':        symbol,
                'signal':        action,
                'action':        action,
                'quantity':      qty,
                # Pass real price fields so PaperExecutor fills at market price
                'price':         ltp,
                'ltp':           ltp,
                'atr':           signal.get('atr', ltp * 0.015),
                'stop_loss':     signal.get('stop_loss', 0),
                'target':        signal.get('target', 0),
                'confidence':    signal.get('confidence', 0),
                'source':        signal.get('source', 'TITAN'),
                'mtf_confirmed': signal.get('mtf_confirmed', False),
                'signal_detail': signal,
            })

            if result.get('success'):
                fill  = result.get('fill_price', ltp)
                slippage = self._calculate_slippage(ltp, fill)
                self.total_trades   += 1
                self.total_slippage += slippage

                if slippage > self.max_slippage_pct:
                    logger.warning(f"High slippage: {slippage:.2%} for {symbol}")

                self.publish_event(EventType.TRADE_EXECUTED, {
                    'symbol':     symbol,
                    'action':     action,
                    'quantity':   result.get('quantity', qty),
                    'fill_price': fill,
                    'slippage':   slippage,
                    'timestamp':  datetime.now().isoformat(),
                })

                logger.info(f"✅ MERCURY executed: {symbol} @ ₹{fill:.2f} (slippage: {slippage:.4%})")
                return {
                    'success':    True,
                    'fill_price': fill,
                    'quantity':   result.get('quantity', qty),
                    'slippage':   slippage,
                    'stop_loss':  result.get('stop_loss', 0),
                }
            else:
                self.failed_trades += 1
                logger.error(f"❌ Execution failed: {symbol} — {result.get('error')}")
                return {'success': False, 'error': result.get('error')}

        except Exception as e:
            self.failed_trades += 1
            logger.error(f"❌ Execution error: {e}", exc_info=True)
            return {'success': False, 'error': str(e)}

    def close_position(self, position: Dict[str, Any]) -> Dict[str, Any]:
        """Close an open position."""
        try:
            result = self.executor.close_position(position)
            if result.get('success'):
                self.publish_event(EventType.POSITION_CLOSED, {
                    'symbol':    position['symbol'],
                    'pnl':       result.get('pnl', 0),
                    'timestamp': datetime.now().isoformat(),
                })
            return result
        except Exception as e:
            logger.error(f"❌ Close position error: {e}", exc_info=True)
            return {'success': False, 'error': str(e)}

    def update_prices(self, prices: Dict[str, float]):
        """
        Push latest prices into the executor.
        Call this every iteration AFTER fetching market data so PaperExecutor
        can update unrealised P&L and auto-trigger stop-losses / targets.
        """
        try:
            if hasattr(self.executor, 'update_prices'):
                self.executor.update_prices(prices)
        except Exception as e:
            logger.warning(f"Price update error: {e}")

    # ── internals ─────────────────────────────────────────────────────────────

    def _calculate_quantity_from_price(self, position_size: float, price: float) -> int:
        """
        Calculate quantity from position size and REAL market price.
        FIXED: was hardcoded to price=2450 which gave wrong qty for every stock.
        """
        if price and price > 0 and position_size > 0:
            qty = int(position_size / price)
        else:
            qty = 1
        return max(qty, 1)

    def _calculate_slippage(self, expected: float, fill: float) -> float:
        if not expected or not fill:
            return 0.0
        return abs(fill - expected) / expected

    def get_stats(self) -> Dict[str, Any]:
        avg_slip = (self.total_slippage / self.total_trades) if self.total_trades else 0.0
        return {
            'name':           'MERCURY',
            'active':         self.is_active,
            'total_trades':   self.total_trades,
            'failed_trades':  self.failed_trades,
            'avg_slippage':   avg_slip,
            'kpi':            'Slippage < 0.15%',
        }
