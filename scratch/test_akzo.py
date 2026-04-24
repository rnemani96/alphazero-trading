import yfinance as yf
try:
    tk = yf.Ticker("AKZOINDIA.NS")
    print(f"Info: {tk.fast_info.last_price}")
    hist = tk.history(period="1d")
    print(f"History: {len(hist)} rows")
except Exception as e:
    print(f"Error: {e}")
