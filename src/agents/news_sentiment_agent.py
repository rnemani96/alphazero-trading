"""News Sentiment Agent"""
import logging
logger = logging.getLogger(__name__)

class NewsSentimentAgent:
    """Analyzes news sentiment"""
    def __init__(self, event_bus, config):
        self.event_bus = event_bus
        self.config = config
    
    def get_sentiment(self, symbols):
        """Get news sentiment for symbols"""
        # Placeholder - in production, fetch real news
        return {'overall': 'NEUTRAL', 'scores': {s: 0.0 for s in symbols}}
