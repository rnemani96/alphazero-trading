"""Sector Agent - Stock Scoring"""
import logging
logger = logging.getLogger(__name__)

class SectorAgent:
    """Scores stocks within a sector"""
    def __init__(self, event_bus, config, sector_name=""):
        self.event_bus = event_bus
        self.config = config
        self.sector_name = sector_name
    
    def score_stocks(self, stocks):
        """Score stocks using multiple factors"""
        scored = []
        for stock in stocks:
            score = self._calculate_score(stock)
            scored.append({**stock, 'score': score})
        return sorted(scored, key=lambda x: x['score'], reverse=True)[:5]
    
    def _calculate_score(self, stock):
        """8-factor scoring model"""
        score = 0
        score += stock.get('momentum', 0) * 0.20
        score += stock.get('trend_strength', 0) * 0.15
        score += stock.get('earnings_quality', 0) * 0.15
        score += stock.get('relative_strength', 0) * 0.15
        score += stock.get('news_sentiment', 0.5) * 0.10
        score += stock.get('volume_confirm', 0) * 0.10
        score += (1 - stock.get('volatility', 0.5)) * 0.10
        score += stock.get('fii_interest', 0) * 0.05
        return score
