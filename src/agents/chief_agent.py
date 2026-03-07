"""Chief Agent - Portfolio Selection"""
import logging
logger = logging.getLogger(__name__)

class ChiefAgent:
    """Selects top 5 stocks from sector agents"""
    def __init__(self, event_bus, config):
        self.event_bus = event_bus
        self.config = config
        self.portfolio = []
    
    def select_portfolio(self, candidate_stocks):
        """Select top 5 stocks based on scores"""
        sorted_stocks = sorted(candidate_stocks, key=lambda x: x['score'], reverse=True)
        self.portfolio = sorted_stocks[:5]
        logger.info(f"Portfolio selected: {[s['symbol'] for s in self.portfolio]}")
        return self.portfolio
