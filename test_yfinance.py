import yfinance as yf
print("Fetching live NIFTY index via yfinance...")
nifty = yf.Ticker("^NSEI")
print(f"Success! NIFTY Current: {nifty.fast_info.last_price}")
