try:
    import nsepython
    print("Fetching live Nifty quote...")
    quote = nsepython.nse_quote("NIFTY")
    if quote:
        print(f"Success! NIFTY Last Price: {quote.get('lastPrice')}")
    else:
        print("Failed to fetch Nifty quote (might be off-market hours or API block).")
except Exception as e:
    print(f"Error: {e}")
