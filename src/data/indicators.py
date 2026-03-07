"""Technical Indicators"""
try:
    import talib
    USE_TALIB = True
except:
    import pandas_ta as ta
    USE_TALIB = False

def add_indicators(df):
    """Add technical indicators to dataframe"""
    if USE_TALIB:
        df['rsi'] = talib.RSI(df['close'], 14)
        df['ema20'] = talib.EMA(df['close'], 20)
        df['ema50'] = talib.EMA(df['close'], 50)
    else:
        df['rsi'] = ta.rsi(df['close'], 14)
        df['ema20'] = ta.ema(df['close'], 20)
        df['ema50'] = ta.ema(df['close'], 50)
    return df
