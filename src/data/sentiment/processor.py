"""
src/data/sentiment/processor.py  —  AlphaZero Capital
══════════════════════════════════════════════════
Batch sentiment inference using ProsusAI/finbert.
Supports efficient tokenization and scoring for multi-agent systems.
"""

import logging, torch
from typing import List, Dict, Any
from transformers import AutoTokenizer, AutoModelForSequenceClassification, pipeline

logger = logging.getLogger("SentimentProcessor")

# Set device (CUDA if available)
DEVICE = 0 if torch.cuda.is_available() else -1

import threading

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

    def process_batch(self, headlines: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Scores a batch of news items using FinBERT if loaded, else fallback."""
        if not headlines:
            return headlines
            
        if not self.loaded:
            logger.info("FinBERT not yet loaded. Using neutral defaults.")
            for h in headlines:
                h['sentiment_label'] = 'NEUTRAL'
                h['sentiment_conf'] = 0.0
                h['sentiment_score'] = 0.0
            return headlines


        texts = [h.get('headline') or h.get('title') or "" for h in headlines]
        valid_indices = [i for i, t in enumerate(texts) if t and len(t) > 10]
        valid_texts = [texts[i] for i in valid_indices]

        if not valid_texts:
            return headlines

        logger.info(f"Processing batch of {len(valid_texts)} headlines...")
        try:
            # Batch inference
            results = self.pipe(valid_texts, batch_size=self.batch_size)
            
            # Map results back to original list
            for idx, res in zip(valid_indices, results):
                label = res['label'].upper()
                score = res['score']
                
                # Convert to numeric score (-1 to 1)
                numeric_score = score if label == 'POSITIVE' else (-score if label == 'NEGATIVE' else 0.0)
                
                headlines[idx]['sentiment_label'] = label
                headlines[idx]['sentiment_conf'] = round(score, 4)
                headlines[idx]['sentiment_score'] = round(numeric_score, 4)
                
            return headlines
        except Exception as e:
            logger.error(f"Inference error: {e}")
            return headlines

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    processor = SentimentProcessor()
    test_data = [
        {"headline": "Market reaches all-time high as interest rates drop"},
        {"headline": "Company reports quarterly loss, shares plunge"},
        {"headline": "RBI maintains status quo on repo rate"}
    ]
    scored = processor.process_batch(test_data)
    for s in scored:
        print(f"[{s.get('sentiment_label')}] {s.get('headline')} (Conf: {s.get('sentiment_conf')})")
