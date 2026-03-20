import logging, torch, re, time
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
from transformers import AutoTokenizer, AutoModelForSequenceClassification, pipeline

logger = logging.getLogger("SentimentProcessor")

# Set device (CUDA if available)
DEVICE = 0 if torch.cuda.is_available() else -1

import threading

# ── LAYER 2: Keyword Engine ──────────────────────────────────────────────────
_KW_POS = {"surge", "rally", "gain", "growth", "jump", "breakout", "bullish", "ath", "upside", "win", "deal", "record profit", "beats estimates"}
_KW_NEG = {"plunge", "slump", "drop", "decline", "weak", "concern", "bearish", "selloff", "halt", "loss", "crash", "fall", "outflow", "miss"}

# ── LAYER 4: India-Specific Rules ───────────────────────────────────────────
_RULES = {
    "record profit": 0.6,
    "beats estimates": 0.6,
    "fii buying": 0.4,
    "upgrade": 0.4,
    "fii selling": -0.4,
    "downgrade": -0.4,
    "rbi maintains": 0.0,
    "rbi unchanged": 0.0,
    "maintains": 0.0,
    "unchanged": 0.0,
}

class SentimentProcessor:
    def __init__(self, model_id: str = "ProsusAI/finbert", batch_size: int = 32):
        self.batch_size = batch_size
        self.model_id = model_id
        self.pipe = None
        self.loaded = False
        self.error = None
        
        # Start background loading
        logger.info(f"Starting background load for {model_id}...")
        threading.Thread(target=self._load_model, daemon=True, name="FinBERTLoader").start()

    def _load_model(self):
        try:
            logger.info(f"Loading FinBERT on {'GPU' if DEVICE == 0 else 'CPU'}...")
            self.pipe = pipeline(
                "text-classification",
                model=self.model_id,
                tokenizer=self.model_id,
                device=DEVICE,
                truncation=True,
                max_length=512
            )
            self.loaded = True
            logger.info("FinBERT model loaded successfully.")
        except Exception as e:
            self.error = str(e)
            logger.error(f"Failed to load FinBERT: {e}")

    def _get_score_kw(self, text: str) -> float:
        """Layer 2: Keyword Engine (Direction)"""
        text = text.lower()
        pos = sum(1 for w in _KW_POS if w in text)
        neg = sum(1 for w in _KW_NEG if w in text)
        if pos > neg: return 1.0
        if neg > pos: return -1.0
        return 0.0

    def _get_score_rules(self, text: str) -> float:
        """Layer 4: India-Specific Rules"""
        text = text.lower()
        score = 0.0
        applied = False
        for rule, val in _RULES.items():
            if rule in text:
                score = val
                applied = True
                # "maintains" or "unchanged" forces neutral
                if val == 0.0: return 0.0
        return score if applied else 0.0

    def _get_score_market(self, symbol: str, news_ts_str: str, fetcher: Any) -> float:
        """Layer 3: Market Signals (REAL EDGE) - 2-5 min after news"""
        if not symbol or not news_ts_str or not fetcher:
            return 0.0
        
        try:
            # Parse news timestamp
            try:
                # Common RSS format: 'Fri, 20 Mar 2026 10:40:00 +0530'
                news_ts = pd.to_datetime(news_ts_str).tz_convert("Asia/Kolkata")
            except:
                news_ts = datetime.now(tz=ZoneInfo("Asia/Kolkata"))

            # Window: 2-5 mins after news
            start_win = news_ts + timedelta(minutes=2)
            end_win   = news_ts + timedelta(minutes=6) # 1m buffer
            
            # Fetch 1m candles around that time
            # Note: fetcher.get_historical usually handles daily, but yfinance supports 1m 
            # for recent 7 days. We'll try to get intraday data.
            # Fetch 1m candles around that time
            # We use fetcher.get_ohlcv or the new bulk fetch if available
            df = fetcher.get_ohlcv(symbol, interval="1m", period="1d")
            if df is None or df.empty:
                return 0.0
            
            # Filter for the specific 2-5 min window
            win_df = df[(df.index >= start_win) & (df.index <= end_win)]
            if win_df.empty: return 0.0
            
            price_start = win_df.iloc[0]['close']
            price_end   = win_df.iloc[-1]['close']
            v_max       = win_df['volume'].max()
            v_avg       = df['volume'].mean() # Baseline from the small window we fetched
            
            p_chg = (price_end - price_start) / price_start if price_start > 0 else 0
            
            # +0.3 -> price up + volume spike (v_max > 1.5x avg)
            # -0.3 -> price down + volume spike
            if abs(p_chg) > 0.001 and v_max > (v_avg * 1.5):
                return 0.3 if p_chg > 0 else -0.3
            
            return 0.0
        except Exception as e:
            logger.debug(f"Market signal error for {symbol}: {e}")
            return 0.0

    def process_batch(self, headlines: List[Dict[str, Any]], fetcher: Optional[Any] = None) -> List[Dict[str, Any]]:
        """Scores a batch using the 4-Layer Hybrid System."""
        if not headlines:
            return headlines
            
        # 1. FinBERT Scores (Batch)
        texts = [h.get('headline') or h.get('title') or "" for h in headlines]
        valid_indices = [i for i, t in enumerate(texts) if t and len(t) > 5]
        
        bert_scores = [0.0] * len(headlines)
        if self.loaded and valid_indices:
            valid_texts = [texts[i] for i in valid_indices]
            try:
                results = self.pipe(valid_texts, batch_size=self.batch_size)
                for i, res in zip(valid_indices, results):
                    label = res['label'].upper()
                    conf = res['score']
                    bert_scores[i] = conf if label == 'POSITIVE' else (-conf if label == 'NEGATIVE' else 0.0)
            except Exception as e:
                logger.error(f"FinBERT batch error: {e}")

        # 2. Hybrid Calculation
        for i, h in enumerate(headlines):
            text = texts[i]
            symbol = h.get('symbol')
            ts = h.get('timestamp')

            s_bert   = bert_scores[i]
            s_kw     = self._get_score_kw(text)
            s_rules  = self._get_score_rules(text)
            s_market = self._get_score_market(symbol, ts, fetcher) if fetcher else 0.0

            # 4-Layer Weighted Formula
            # 0.4 * BERT + 0.2 * KW + 0.3 * MARKET + 0.1 * RULES
            final_score = (0.4 * s_bert) + (0.2 * s_kw) + (0.3 * s_market) + (0.1 * s_rules)
            
            # Bias Thresholds
            if final_score > 0.2:
                label = 'BUY'
            elif final_score < -0.2:
                label = 'SELL'
            else:
                label = 'NEUTRAL'

            h['sentiment_label'] = label
            h['sentiment_score'] = round(final_score, 4)
            h['layer_scores'] = {
                'bert': round(s_bert, 3),
                'kw': s_kw,
                'market': s_market,
                'rules': s_rules
            }

        return headlines

if __name__ == "__main__":
    import pandas as pd
    # Mocking for standalone test
    class MockFetcher:
        def get_historical(self, *a, **k): return None
        
    logging.basicConfig(level=logging.INFO)
    processor = SentimentProcessor()
    while not processor.loaded: time.sleep(1) # wait for load in test
    
    test_data = [
        {"headline": "RELIANCE reports record profit, surge in margins", "symbol": "RELIANCE"},
        {"headline": "Corporate crash after FII selling spree", "symbol": "TCS"},
        {"headline": "RBI maintains repo rate, unchanged stance"},
        {"headline": "Market rally as FII buying continues"}
    ]
    scored = processor.process_batch(test_data, fetcher=MockFetcher())
    for s in scored:
        print(f"[{s['sentiment_label']}] Score: {s['sentiment_score']} | Layers: {s['layer_scores']}")
        print(f"   {s['headline']}\n")
