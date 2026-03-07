"""Trade Logger"""
import logging
logger = logging.getLogger(__name__)

class TradeLogger:
    """Logs all trades"""
    def __init__(self):
        self.trades = []
    
    def log_trade(self, signal, result):
        """Log a trade"""
        self.trades.append({'signal': signal, 'result': result})
        logger.info(f"Trade logged: {signal['symbol']} {signal['signal']}")
