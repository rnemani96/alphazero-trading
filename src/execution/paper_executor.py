"""Paper Trading Executor"""
import logging
logger = logging.getLogger(__name__)

class PaperExecutor:
    """Simulates trades for paper trading"""
    def __init__(self, config):
        self.config = config
        self.capital = config.get('INITIAL_CAPITAL', 1000000)
    
    def execute_trade(self, signal):
        """Simulate trade execution"""
        logger.info(f"[PAPER] Executing {signal['signal']} for {signal['symbol']}")
        return {'success': True, 'fill_price': 2450.50, 'quantity': 10, 'stop_loss': 2400}
    
    def close_position(self, position):
        """Simulate position close"""
        logger.info(f"[PAPER] Closing {position['symbol']}")
        return {'success': True, 'pnl': 850}

    def get_positions(self) -> dict:
        """Return current open positions. Paper mode tracks filled trades."""
        return getattr(self, '_positions', {})

    def _record_position(self, symbol: str, result: dict, signal: dict):
        """Called after a successful execute_trade to track the position."""
        if not hasattr(self, '_positions'):
            self._positions = {}
        if result.get('success'):
            self._positions[symbol] = {
                'symbol':        symbol,
                'side':          signal.get('signal', 'BUY'),
                'quantity':      result.get('quantity', 0),
                'entry_price':   result.get('fill_price', 0),
                'current_price': result.get('fill_price', 0),
                'stop_loss':     result.get('stop_loss', 0),
                'unrealised_pnl': 0.0,
                'source':        signal.get('source', '—'),
                'mtf_confirmed': signal.get('mtf_confirmed', False),
            }
