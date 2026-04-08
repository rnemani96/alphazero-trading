import sys
import os
import pandas as pd
import numpy as np
import logging
from datetime import datetime, timedelta

# Mock the environment so we can import src
sys.path.insert(0, os.getcwd())

from src.agents.titan_agent import TitanAgent
from src.risk.position_sizer import PositionSizer
from src.data.indicators import add_all_indicators

logging.basicConfig(level=logging.ERROR) # Mute extra logs
logger = logging.getLogger("Bench")

def run_bench():
    import yfinance as yf
    symbol = "RELIANCE.NS"
    # Fetch 6 months instead of 1 year for speed
    df = yf.download(symbol, period="6mo", interval="1d", progress=False)
    if df.empty:
        return
    
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df.columns = [c.lower() for c in df.columns]
    
    df = add_all_indicators(df)
    df = df.dropna(subset=['atr', 'rsi', 'ema20', 'ema50'])
    
    REGIME = "SIDEWAYS"
    CAPITAL = 100000.0
    
    config = {'TITAN_MIN_CONFIDENCE': 0.40, 'TITAN_MIN_AGREEMENT': 2}
    titan = TitanAgent(None, config)
    sizer = PositionSizer(total_capital=CAPITAL)
    
    legacy_trades = 0
    legacy_total_risk = 0.0
    new_trades = 0
    new_total_risk = 0.0
    count = 0

    # Test last 30 trading days
    for i in range(len(df) - 30, len(df)):
        window = df.iloc[:i+1]
        row = df.iloc[i]
        price = row['close']
        atr = row['atr']
        count += 1
        
        md = {symbol: window}
        signals = titan.generate_signals(md, regime=REGIME)
        
        if signals:
            sig = signals[0]
            res = sizer.size(sig['top_strategy'], price, atr, regime=REGIME)
            if res['qty'] > 0:
                new_trades += 1
                new_total_risk += res['risk_amount']

        # BEFORE LOGIC SIMULATION
        titan_legacy = TitanAgent(None, {'TITAN_MIN_CONFIDENCE': 0.25, 'TITAN_MIN_AGREEMENT': 1})
        signals_legacy = titan_legacy.generate_signals(md, regime=REGIME)
        if signals_legacy:
            l_qty = int(15000 / price)
            l_risk = (3.0 * atr) * l_qty # 3x ATR stop
            legacy_trades += 1
            legacy_total_risk += l_risk

    print("\n" + "="*60)
    print(f"STABILIZATION BENCHMARK: {symbol} in {REGIME} Regime")
    print("="*60)
    print(f"Results over last {count} days:")
    print(f"  LEGACY (BEFORE):")
    print(f"    Trades Triggered: {legacy_trades}")
    print(f"    Total Risk:        ₹{legacy_total_risk:,.0f}")
    
    print(f"\n  STABILIZED (AFTER):")
    print(f"    Trades Triggered: {new_trades}")
    print(f"    Total Risk:        ₹{new_total_risk:,.0f}")
    
    improvement = (1 - new_total_risk/max(1, legacy_total_risk)) * 100
    print("\n" + "-"*60)
    print(f"TOTAL EXPOSURE REDUCTION: {improvement:.1f}%")
    print("="*60)

if __name__ == "__main__":
    run_bench()
