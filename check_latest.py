import yfinance as yf
from datetime import datetime
sym = "RELIANCE.NS"
df = yf.download(sym, period="1mo", progress=False)
if not df.empty:
    print(f"Latest data for {sym}: {df.index[-1]}")
else:
    print(f"Failed to download data for {sym}")
