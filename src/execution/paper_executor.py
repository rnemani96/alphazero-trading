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
