
import os
import sys
from zoneinfo import ZoneInfo
from datetime import datetime

# Add root to path
sys.path.append('d:\\files\\ALPHAZERO_COMPLETE_FINAL\\ALPHAZERO_COMPLETE')

from src.data.multi_source_data import get_msd

def test_fetch():
    msd = get_msd()
    symbols = ['PGEL', 'SUZLON', 'BANDHANBNK', 'ZOMATO']
    print(f"Testing fetch for {symbols}...")
    
    quotes = msd.get_bulk_quotes(symbols)
    for s in symbols:
        q = quotes.get(s, {})
        print(f"Symbol: {s:12} | Price: {q.get('ltp', 0):8.2f} | Source: {q.get('source', 'N/A')}")
    
    print("\nTesting single quote...")
    for s in symbols:
        q = msd.get_quote(s)
        print(f"Symbol: {s:12} | Price: {q.get('ltp', 0):8.2f} | Source: {q.get('source', 'N/A')}")

if __name__ == "__main__":
    test_fetch()
