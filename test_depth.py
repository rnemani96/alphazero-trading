import collections
import collections.abc
collections.Callable = collections.abc.Callable
try:
    from nsepython import nse_quote
    quote = nse_quote("RELIANCE")
    print(list(quote.keys())[:10])
    
    # Check if we have order book
    if 'priceInfo' in quote:
        print("priceInfo:", quote['priceInfo'])
    if 'preOpenMarket' in quote:
        print("preOpenMarket:", quote['preOpenMarket'])
except Exception as e:
    print("Error:", e)
