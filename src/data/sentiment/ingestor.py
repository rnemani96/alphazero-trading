"""
src/data/sentiment/ingestor.py  —  AlphaZero Capital
══════════════════════════════════════════════════
Handles news ingestion from RSS feeds and yfinance.
Includes deduplication and text cleaning.
"""

import logging, re, hashlib, time
from typing import List, Dict, Any, Set
import requests
import xml.etree.ElementTree as ET
from datetime import datetime

logger = logging.getLogger("Ingestor")

RSS_SOURCES = [
    {'url': 'https://www.moneycontrol.com/rss/MCtopnews.xml',                          'name': 'Moneycontrol', 'weight': 1.0},
    {'url': 'https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms',     'name': 'ET Markets',   'weight': 1.0},
    {'url': 'https://www.livemint.com/rss/markets',                                     'name': 'LiveMint',     'weight': 0.8},
    {'url': 'https://www.business-standard.com/rss/markets-106.rss',                   'name': 'BS Markets',   'weight': 0.8},
    {'url': 'https://feeds.feedburner.com/ndtvprofit-latest',                           'name': 'NDTV Profit',   'weight': 0.7},
]

class NewsIngestor:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AlphaZero/5.0 (News Pipeline)'
        })
        self._seen_hashes: Set[str] = set()

    def clean_text(self, text: str) -> str:
        """Removes HTML tags, ads, and noise."""
        if not text: return ""
        # Remove HTML tags
        text = re.sub(r'<[^>]+>', '', text)
        # Remove common ad patterns or noise
        text = re.sub(r'Subscribe to .* for more.*', '', text, flags=re.I)
        text = re.sub(r'Also Read:.*', '', text, flags=re.I)
        # Normalize whitespace
        text = " ".join(text.split())
        return text

    def get_hash(self, text: str) -> str:
        """Simple hash for deduplication."""
        return hashlib.md5(text.lower().encode()).hexdigest()

    def fetch_rss(self) -> List[Dict[str, Any]]:
        """Fetches and parses all RSS feeds."""
        all_news = []
        for src in RSS_SOURCES:
            try:
                r = self.session.get(src['url'], timeout=10)
                if r.status_code != 200: continue
                
                root = ET.fromstring(r.text)
                items = root.findall('.//item')
                for item in items:
                    title = item.find('title')
                    desc = item.find('description')
                    link = item.find('link')
                    pub_date = item.find('pubDate')
                    
                    headline = self.clean_text(title.text if title is not None else "")
                    body = self.clean_text(desc.text if desc is not None else "")
                    
                    if not headline: continue
                    
                    h = self.get_hash(headline)
                    if h in self._seen_hashes: continue
                    self._seen_hashes.add(h)
                    
                    all_news.append({
                        'headline': headline,
                        'body': body,
                        'source': src['name'],
                        'weight': src['weight'],
                        'url': link.text if link is not None else "",
                        'timestamp': pub_date.text if pub_date is not None else datetime.now().isoformat(),
                        'type': 'RSS'
                    })
            except Exception as e:
                logger.debug(f"RSS Ingestion error for {src['name']}: {e}")
        
        return all_news

    def fetch_yfinance_news(self, symbols: List[str]) -> List[Dict[str, Any]]:
        """Fetches stock-specific news from yfinance."""
        import yfinance as yf
        y_news = []
        for sym in symbols[:20]:  # Limit to top 20 for speed
            try:
                t = yf.Ticker(f"{sym}.NS")
                # Handle different yfinance versions
                news_items = []
                try: news_items = t.get_news() or []
                except: news_items = getattr(t, 'news', []) or []
                
                for item in news_items[:10]:
                    title = item.get('title') or item.get('content', {}).get('title') or ""
                    headline = self.clean_text(title)
                    if not headline: continue
                    
                    h = self.get_hash(headline)
                    if h in self._seen_hashes: continue
                    self._seen_hashes.add(h)
                    
                    y_news.append({
                        'headline': headline,
                        'body': '', # yfinance usually only gives snippets
                        'source': item.get('publisher') or 'yfinance',
                        'weight': 1.2, # Direct stock news has higher weight
                        'url': item.get('link') or '',
                        'timestamp': datetime.now().isoformat(), # yfinance news timestamp parsing is messy
                        'symbol': sym,
                        'type': 'YF'
                    })
            except Exception as e:
                logger.debug(f"YF Ingestion error for {sym}: {e}")
        
        return y_news

    def ingest_all(self, symbols: List[str] = []) -> List[Dict[str, Any]]:
        """Main entry point for ingestion."""
        rss = self.fetch_rss()
        yf_news = self.fetch_yfinance_news(symbols)
        logger.info(f"Ingested {len(rss)} RSS and {len(yf_news)} YF headlines.")
        return rss + yf_news

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    ingestor = NewsIngestor()
    results = ingestor.ingest_all(['RELIANCE', 'TCS'])
    for r in results[:5]:
        print(f"[{r['source']}] {r['headline']}")
