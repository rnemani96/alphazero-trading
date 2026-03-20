import sys, os
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parents[0]
sys.path.append(str(ROOT))

import logging
logging.basicConfig(level=logging.INFO)

from src.data.fetch import DataFetcher
from src.data.sentiment.processor import SentimentProcessor
from src.risk.position_sizer import PositionSizer

def test_macro():
    print("\n--- Testing Macro Reliability ---")
    cfg = {"INITIAL_CAPITAL": 1000000}
    fetcher = DataFetcher(cfg)
    macro = fetcher.get_macro_data()
    print(f"Macro Data: {macro}")
    assert 'status' in macro
    assert macro['status'] in ['LIVE', 'FFILL', 'MISSING']
    print("✓ Macro Reliability OK")

def test_sentiment():
    print("\n--- Testing Sentiment Correction Layer ---")
    processor = SentimentProcessor()
    # Wait for model (in a real test we'd wait, but here we can check rule-based part)
    test_data = [
        {"headline": "RELIANCE reports record profit, surge in margins", "symbol": "RELIANCE", "timestamp": str(datetime.now())},
        {"headline": "Corporate crash after FII selling spree", "symbol": "TCS", "timestamp": str(datetime.now())},
        {"headline": "RBI maintains repo rate, unchanged stance", "timestamp": str(datetime.now())},
    ]
    # We'll skip market confirmation to avoid network hits in this test
    scored = processor.process_batch(test_data, fetcher=None)
    for s in scored:
        print(f"[{s['sentiment_label']}] {s['headline']}")
        print(f"   Score: {s['sentiment_score']} | Layers: {s['layer_scores']}")
        
    # Check overrides
    assert scored[0]['sentiment_score'] > 0.4 # record profit boost
    assert scored[1]['sentiment_score'] < -0.3 # crash/selling
    assert scored[2]['sentiment_score'] == 0.0 # maintains -> neutral
    print("✓ Sentiment Correction Layer OK")

def test_sizer():
    print("\n--- Testing Position Sizer Discounts ---")
    sizer = PositionSizer(total_capital=1000000)
    
    q_live = sizer.size("TEST", 2500, 30, 15, "LIVE")['qty']
    q_ffill = sizer.size("TEST", 2500, 30, 15, "FFILL")['qty']
    q_missing = sizer.size("TEST", 2500, 30, 15, "MISSING")['qty']
    
    print(f"Qty (LIVE): {q_live}")
    print(f"Qty (FFILL): {q_ffill} (Expected ~80% of {q_live})")
    print(f"Qty (MISSING): {q_missing} (Expected ~60% of {q_live})")
    
    assert q_ffill <= q_live * 0.85
    assert q_missing <= q_live * 0.65
    print("✓ Position Sizer Discounts OK")

if __name__ == "__main__":
    try:
        test_macro()
        test_sentiment()
        test_sizer()
        print("\nALL PHASE 25 TESTS PASSED!")
    except Exception as e:
        print(f"\nTEST FAILED: {e}")
        import traceback
        traceback.print_exc()
