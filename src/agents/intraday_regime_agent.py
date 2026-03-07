"""Intraday Regime Detection Agent"""
import logging
logger = logging.getLogger(__name__)

class IntradayRegimeAgent:
    """Detects market regime"""
    def __init__(self, event_bus, config):
        self.event_bus = event_bus
        self.config = config
    
    def detect_regime(self, market_data):
        """Detect current market regime"""
        adx = market_data.get('adx', 20)
        atr = market_data.get('atr', 50)
        vix = market_data.get('india_vix', 15)
        
        if adx > 25 and atr > 60:
            return 'TRENDING'
        elif vix > 20:
            return 'VOLATILE'
        elif adx < 20:
            return 'SIDEWAYS'
        else:
            return 'RISK_OFF'
