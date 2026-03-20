from src.data.fetch import DataFetcher, _to_yahoo

print("1. _to_yahoo output for 'INOXWIND:SWING.NS':", _to_yahoo('INOXWIND:SWING.NS'))

fetcher = DataFetcher({'MODE': 'PAPER', 'DATA_CACHE_TTL': 0})
print("\n2. Calling _batch_fetch_quotes")
try:
    fetcher._batch_fetch_quotes(['INOXWIND:SWING.NS', 'CANBK:SWING.NS', 'LLOYDSME:SWING.NS'])
except Exception as e:
    print("Exception in batch quote:", e)

print("\n3. Calling get_ohlcv for 'INOXWIND:SWING.NS'")
try:
    fetcher.get_ohlcv('INOXWIND:SWING.NS', interval='15min', bars=60)
except Exception as e:
    print("Exception in get_ohlcv:", e)
