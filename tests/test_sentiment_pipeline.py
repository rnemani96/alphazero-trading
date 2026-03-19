"""
tests/test_sentiment_pipeline.py  —  AlphaZero Capital
═══════════════════════════════════════════════════
End-to-end test for the FinBERT sentiment pipeline.
"""

import os, sys, logging
from datetime import datetime

# Setup paths
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(ROOT)

from src.data.sentiment.ingestor import NewsIngestor
from src.data.sentiment.processor import SentimentProcessor
from src.data.sentiment.storage import SentimentStorage, SentimentAggregator

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("TestPipeline")

def run_test():
    logger.info("Starting End-to-End Sentiment Pipeline Test...")
    
    # 1. Ingestion
    ingestor = NewsIngestor()
    symbols = ['RELIANCE', 'TCS', 'HDFCBANK']
    raw_news = ingestor.ingest_all(symbols)
    logger.info(f"Step 1: Ingested {len(raw_news)} headlines.")
    
    if not raw_news:
        logger.warning("No news ingested. Check internet connection or RSS URLs.")
        return

    # 2. Processing (FinBERT)
    processor = SentimentProcessor(batch_size=16)
    processed_news = processor.process_batch(raw_news[:20]) # Test with first 20
    logger.info(f"Step 2: Processed {len(processed_news)} headlines with FinBERT.")
    
    # 3. Storage
    storage = SentimentStorage(storage_dir="data/test_sentiment")
    storage.save_headlines(processed_news)
    logger.info(f"Step 3: Saved headlines to data/test_sentiment/")
    
    # 4. Aggregation
    aggregator = SentimentAggregator(storage)
    metrics = aggregator.compute_daily_metrics()
    logger.info("Step 4: Aggregated Metrics:")
    for k, v in metrics.items():
        logger.info(f"  - {k}: {v}")
    
    logger.info("End-to-End Test Complete ✓")

if __name__ == "__main__":
    run_test()
