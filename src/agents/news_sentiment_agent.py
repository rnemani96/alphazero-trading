"""
HERMES Agent — News & Sentiment Analysis
src/agents/news_sentiment_agent.py

FIXES vs previous:
  1. NSE RSS URL was wrong (JSON endpoint, not RSS) — removed, replaced with 5 working feeds
  2. yfinance news: new versions changed API (get_news vs .news, and content structure)
  3. Keyword dict extended with more Indian market terms
"""

import logging, threading, re
from datetime import datetime
from typing import Dict, Any, List, Optional

logger = logging.getLogger("HERMES")

try:
    import requests
    _REQ = True
except ImportError:
    _REQ = False

try:
    import yfinance as yf
    _YF = True
except ImportError:
    _YF = False

try:
    from transformers import pipeline as _hf_pipeline
    _FINBERT_PIPELINE = _hf_pipeline("text-classification", model="ProsusAI/finbert",
                                      truncation=True, max_length=512)
    _FINBERT = True
    logger.info("HERMES: FinBERT loaded ✓")
except Exception:
    _FINBERT = False
    _FINBERT_PIPELINE = None

try:
    from ..event_bus.event_bus import BaseAgent, EventType
except ImportError:
    try:
        from src.event_bus.event_bus import BaseAgent, EventType
    except ImportError:
        class BaseAgent:
            def __init__(self, event_bus, config, name=""):
                self.event_bus = event_bus; self.config = config
                self.name = name; self.is_active = True
            def publish_event(self, *a, **k): pass
        class EventType:
            SIGNAL_GENERATED = "SIGNAL_GENERATED"

_POS = {
    'beat':2,'beats':2,'record':2,'profit':1,'growth':2,'surge':2,'rally':2,
    'gain':1,'jump':2,'upgraded':2,'outperform':2,'strong':1,'robust':1,
    'buyback':2,'dividend':1,'approved':1,'deal':1,'contract':1,'wins':1,
    'inflow':1,'fii buying':2,'rate cut':2,'stimulus':1,'recovery':1,
    'bullish':2,'breakout':2,'all-time high':2,'ath':2,'upside':1,'capex':1,
}
_NEG = {
    'miss':-2,'misses':-2,'loss':-2,'losses':-2,'decline':-1,'fall':-1,
    'drop':-1,'plunge':-2,'slump':-2,'weak':-1,'downgrade':-2,'underperform':-2,
    'fraud':-3,'default':-3,'penalty':-2,'probe':-2,'investigation':-2,
    'lawsuit':-2,'fii selling':-2,'fii outflow':-2,'rate hike':-2,
    'crash':-3,'selloff':-2,'sell-off':-2,'halt':-2,'bearish':-2,
    'outflow':-1,'concern':-1,'down':-1,'lower':-1,'cut':-1,
}

# FIXED: correct working RSS URLs for Indian markets
RSS_SOURCES = [
    ('https://www.moneycontrol.com/rss/MCtopnews.xml',                          'Moneycontrol', 12),
    ('https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms',     'ET Markets',   12),
    ('https://www.livemint.com/rss/markets',                                     'LiveMint',     10),
    ('https://www.business-standard.com/rss/markets-106.rss',                   'BS Markets',   10),
    ('https://feeds.feedburner.com/ndtvprofit-latest',                           'NDTV Profit',   8),
]

def _mean(vals): return sum(vals)/len(vals) if vals else 0.0


from src.data.sentiment.ingestor import NewsIngestor
from src.data.sentiment.processor import SentimentProcessor
from src.data.sentiment.storage import SentimentStorage, SentimentAggregator

class NewsSentimentAgent(BaseAgent):

    def __init__(self, event_bus, config: Dict, data_fetcher: Optional[Any] = None):
        super().__init__(event_bus=event_bus, config=config, name="HERMES")
        self._lock  = threading.Lock()
        
        # Initialise Pipeline Components
        self.ingestor = NewsIngestor()
        self.fetcher  = data_fetcher
        self.processor = SentimentProcessor(batch_size=config.get('FINBERT_BATCH_SIZE', 32))
        self.storage = SentimentStorage()
        self.aggregator = SentimentAggregator(self.storage)
        
        self._cache: Optional[Dict] = None
        self._cache_ts: Optional[datetime] = None
        self._ttl   = config.get('HERMES_CACHE_TTL', 900)
        
        self._headlines_processed = 0
        logger.info(f"HERMES Agent initialised with 4-Layer Hybrid Sentiment Pipeline.")

    def get_sentiment(self, symbols: List[str]) -> Dict[str, Any]:
        """
        Main entry point for sentiment analysis.
        Ingests, processes, stores, and aggregates news signals.
        """
        with self._lock:
            if self._cache and self._cache_ts:
                if (datetime.now() - self._cache_ts).total_seconds() < self._ttl:
                    return dict(self._cache)

        try:
            # 1. Ingest News
            raw_news = self.ingestor.ingest_all(symbols)
            
            # 2. Process with 4-Layer Hybrid System
            processed_news = self.processor.process_batch(raw_news, fetcher=self.fetcher)
            
            # 3. Store for persistence and aggregation
            self.storage.save_headlines(processed_news)
            
            # 4. Aggregate Metrics
            metrics = self.aggregator.compute_daily_metrics()
            
            # 5. Extract per-symbol scores for backward compatibility
            sym_scores = {s: 0.0 for s in symbols}
            for n in processed_news:
                s = n.get('symbol')
                if s in sym_scores and 'sentiment_score' in n:
                    # Rolling average for multi-source headlines
                    sym_scores[s] = (sym_scores[s] + n['sentiment_score']) / 2 if sym_scores[s] != 0 else n['sentiment_score']
            
            overall_score = metrics.get('sentiment_score', 0.0)
            if not isinstance(overall_score, (int, float)):
                try: overall_score = float(overall_score)
                except: overall_score = 0.0

            if overall_score > 0.2:
                overall = 'BUY'
            elif overall_score < -0.2:
                overall = 'SELL'
            else:
                overall = 'NEUTRAL'
            
            result = {
                'overall':       overall,
                'overall_score': round(overall_score, 4),
                'score':         round(overall_score, 4),
                'momentum':      metrics.get('sentiment_momentum', 0.0),
                'volatility':    metrics.get('sentiment_volatility', 0.0),
                'volume':        metrics.get('news_volume', 0),
                'extreme_flag':  metrics.get('extreme_sentiment_flag', 0),
                'scores':        sym_scores,
                'metrics':       metrics,
                'headlines':     processed_news[:20],  # Included for dashboard
                'timestamp':     datetime.now().isoformat(),
            }
            
            with self._lock:
                self._cache = result
                self._cache_ts = datetime.now()
                self._headlines_processed += len(processed_news)

            logger.info(f"HERMES → score={result.get('overall_score', 0.0):+.3f} | bias={overall} | vol={result.get('volume', 0)} | regime_hint={metrics.get('regime_hint', 'NEUTRAL')}")
            if processed_news:
                top = processed_news[0]
                logger.debug(f"HERMES Top Signal: {top.get('headline')} | Score: {top.get('sentiment_score')} | Layers: {top.get('layer_scores')}")
                
            return result

        except Exception as e:
            logger.error(f"HERMES full pipeline error: {type(e).__name__} - {e}")
            import traceback
            logger.debug(traceback.format_exc())
            return {
                'overall': 'NEUTRAL',
                'overall_score': 0.0,
                'score': 0.0,
                'momentum': 0.0,
                'volume': 0,
                'scores': {s: 0.0 for s in symbols},
                'error': str(e)
            }

    def get_symbol_sentiment(self, symbol: str) -> float:
        with self._lock:
            if self._cache:
                return self._cache.get('scores', {}).get(symbol, 0.0)
        return 0.0

    def get_stats(self) -> Dict[str, Any]:
        with self._lock:
            score = self._cache.get('score', 0.0) if self._cache else 0.0
            vol = self._cache.get('volume', 0) if self._cache else 0
        return {
            'name': 'HERMES',
            'active': self.is_active,
            'current_score': score,
            'headlines_total': self._headlines_processed,
            'last_volume': vol
        }


