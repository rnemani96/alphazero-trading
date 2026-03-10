import sys
import os
import logging

# Add project root to path
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from src.agents.sector_agent import SectorAgent
from src.event_bus.event_bus import EventBus

# Setup minimal logging
logging.basicConfig(level=logging.INFO)

def test_atlas():
    bus = EventBus()
    config = {}
    atlas = SectorAgent(bus, config)
    
    # 1. Test regime allocation
    print("\n--- Testing Regime Allocation ---")
    for regime in ['TRENDING', 'SIDEWAYS', 'VOLATILE', 'RISK_OFF', 'NEUTRAL']:
        alloc = atlas.get_sector_allocation(regime)
        top_sector = max(alloc, key=alloc.get)
        print(f"Regime: {regime:10} | Top Sector: {top_sector:10} | Weight: {alloc[top_sector]:.2f}")

    # 2. Test stock scoring
    print("\n--- Testing Stock Scoring ---")
    test_stocks = [
        {'symbol': 'HDFCBANK', 'momentum': 0.8, 'trend_strength': 0.7, 'earnings_quality': 0.9},
        {'symbol': 'TCS',      'momentum': 0.4, 'trend_strength': 0.4, 'earnings_quality': 0.8},
        {'symbol': 'RELIANCE', 'momentum': 0.9, 'trend_strength': 0.9, 'volatility': 0.8}, # High vol should hurt score
    ]
    
    scored = atlas.score_stocks(test_stocks)
    for s in scored:
        print(f"Symbol: {s['symbol']:10} | Sector: {s['sector']:10} | Score: {s['atlas_score']:.4f}")

    print("\n--- Testing Stats ---")
    print(atlas.get_stats())
    
    print("\n✅ ATLAS Verification Complete")

if __name__ == "__main__":
    test_atlas()
