import pandas as pd
from datetime import datetime
import numpy as np

periods = 10
print(f"Pandas version: {pd.__version__}")

freqs = ['1min', '5min', '15min', '1hour', '1day', '1T', 'T', '1m', '5m', '15m']

for f in freqs:
    try:
        dr = pd.date_range(end=datetime.now(), periods=periods, freq=f)
        print(f"Successfully used freq: {f}")
    except Exception as e:
        print(f"FAILED to use freq: {f} -> {e}")

try:
    # Test internal conversion
    offset = pd.tseries.frequencies.to_offset('1min')
    print(f"Offset for '1min': {offset} (freq_str: {offset.freqstr})")
    dr = pd.date_range(end=datetime.now(), periods=periods, freq=offset)
    print(f"Successfully used offset object from '1min'")
except Exception as e:
    print(f"FAILED to use offset object from '1min' -> {e}")
