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


class NewsSentimentAgent(BaseAgent):

    def __init__(self, event_bus, config: Dict):
        super().__init__(event_bus=event_bus, config=config, name="HERMES")
        self._lock  = threading.Lock()
        self._cache: Optional[Dict] = None
        self._cache_ts: Optional[datetime] = None
        self._ttl   = config.get('HERMES_CACHE_TTL', 900)
        self._headlines_processed = 0
        self._api_calls = 0
        logger.info(f"HERMES Agent initialised — {'FinBERT' if _FINBERT else 'Keyword'} scoring, {'yfinance' if _YF else 'RSS only'}")

    def get_sentiment(self, symbols: List[str]) -> Dict[str, Any]:
        with self._lock:
            if self._cache and self._cache_ts:
                if (datetime.now() - self._cache_ts).total_seconds() < self._ttl:
                    return dict(self._cache)

        headlines = self._fetch_headlines(symbols)
        scored    = self._score_headlines(headlines, symbols)

        sym_scores = {s: [] for s in symbols}
        for h in scored:
            sym = h.get('symbol', '')
            if sym in sym_scores:
                sym_scores[sym].append(h['score'])
        per_sym = {s: (_mean(v) if v else 0.0) for s, v in sym_scores.items()}
        overall_score = _mean(list(per_sym.values()))

        overall = 'POSITIVE' if overall_score >= 0.15 else 'NEGATIVE' if overall_score <= -0.15 else 'NEUTRAL'

        result = {
            'overall':   overall, 'score': round(overall_score, 3),
            'scores':    {s: round(v, 3) for s, v in per_sym.items()},
            'headlines': scored[:30],
            'timestamp': datetime.now().isoformat(),
        }
        with self._lock:
            self._cache = result; self._cache_ts = datetime.now()

        pos = len([h for h in scored if h.get('score',0) > 0])
        neg = len([h for h in scored if h.get('score',0) < 0])
        logger.info(f"HERMES → overall={overall} (score={overall_score:+.3f}) | {len(scored)} headlines | {pos} pos / {neg} neg")
        return result

    def get_symbol_sentiment(self, symbol: str) -> float:
        with self._lock:
            if self._cache:
                return self._cache.get('scores', {}).get(symbol, 0.0)
        return 0.0

    def _fetch_headlines(self, symbols: List[str]) -> List[Dict]:
        all_headlines = []

        # yfinance news — per symbol (best quality, actual stock-specific news)
        if _YF:
            for sym in symbols[:15]:
                try:
                    ticker = yf.Ticker(f"{sym}.NS")
                    # Support both old (.news) and new (.get_news()) yfinance API
                    try:
                        news = ticker.get_news() or []
                    except AttributeError:
                        news = getattr(ticker, 'news', []) or []
                    self._api_calls += 1
                    for item in news[:6]:
                        # Handle both old and new yfinance news schema
                        title = (item.get('title') or
                                 item.get('content', {}).get('title') or '')
                        publisher = (item.get('publisher') or
                                     item.get('source', {}).get('name') or 'yfinance')
                        if title:
                            all_headlines.append({'title': title, 'source': publisher, 'symbol': sym})
                except Exception:
                    pass

        # RSS feeds — market-wide news
        for url, source, limit in RSS_SOURCES:
            all_headlines.extend(self._fetch_rss(url, source, limit))

        self._headlines_processed += len(all_headlines)
        return all_headlines

    def _fetch_rss(self, url: str, source: str, limit: int = 10) -> List[Dict]:
        if not _REQ:
            return []
        try:
            r = requests.get(url, timeout=6, headers={'User-Agent': 'Mozilla/5.0 AlphaZero/1.0'})
            if r.status_code != 200:
                return []
            self._api_calls += 1
            titles = re.findall(r'<title><!\[CDATA\[(.*?)\]\]></title>', r.text, re.DOTALL)
            if not titles:
                titles = re.findall(r'<title>(.*?)</title>', r.text)
            results = []
            for t in titles[1:limit+1]:
                t = re.sub(r'<[^>]+>', '', t).strip()
                if t and len(t) > 10:
                    results.append({'title': t, 'source': source, 'symbol': ''})
            return results
        except Exception:
            return []

    def _score_headlines(self, headlines: List[Dict], symbols: List[str]) -> List[Dict]:
        sym_upper = {s.upper(): s for s in symbols}
        scored = []
        for h in headlines:
            title = h.get('title', '')
            if not title:
                continue
            sym = h.get('symbol', '')
            if not sym:
                tu = title.upper()
                for su, so in sym_upper.items():
                    if su in tu:
                        sym = so; break
            score = self._finbert_score(title) if (_FINBERT and _FINBERT_PIPELINE) else self._keyword_score(title)
            scored.append({**h, 'symbol': sym, 'score': score})
        return scored

    def _finbert_score(self, text: str) -> float:
        try:
            r = _FINBERT_PIPELINE(text)[0]
            c = r['score']
            return c if r['label'].lower()=='positive' else (-c if r['label'].lower()=='negative' else 0.0)
        except Exception:
            return self._keyword_score(text)

    def _keyword_score(self, text: str) -> float:
        tl = text.lower()
        s  = sum(w for k, w in _POS.items() if k in tl)
        s += sum(w for k, w in _NEG.items() if k in tl)
        return max(-1.0, min(1.0, s / 5.0))

    def get_stats(self) -> Dict[str, Any]:
        with self._lock:
            overall = self._cache.get('overall','NEUTRAL') if self._cache else 'NEUTRAL'
        return {'name':'HERMES','active':self.is_active,'overall':overall,
                'headlines_processed':self._headlines_processed,'finbert_active':_FINBERT}
