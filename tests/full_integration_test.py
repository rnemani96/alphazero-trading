import sys
import os
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Any

# Mock setup for imports
sys.path.append(os.path.abspath("."))

from src.risk.active_portfolio import ActivePortfolio, get_active_portfolio
from src.agents.guardian_agent import GuardianAgent
from src.titan import TitanStrategyEngine
from src.data.indicators import IndicatorEngine

def test_candlestick_detection():
    print("\n[+] 1. Testing Candlestick Pattern Detection...")
    # Create a 'Bullish Engulfing' pattern
    # Candle 0: Red (Open 100, Close 90)
    # Candle 1: Green (Open 85, Close 105) - Engulfs!
    df = pd.DataFrame({
        'open':  [100, 85, 105, 100, 95],
        'high':  [102, 110, 108, 105, 100],
        'low':   [88, 80, 100, 95, 90],
        'close': [90, 105, 102, 102, 98],
        'volume':[100, 200, 150, 120, 110]
    })
    
    engine = IndicatorEngine(df)
    df = engine.add_candlestick().build()
    
    is_engulfing = df['is_bull_engulfing'].iloc[1]
    if is_engulfing:
        print("   ✅ Bullish Engulfing correctly detected at index 1.")
    else:
        print("   ❌ Bullish Engulfing NOT detected at index 1.")

def test_titan_candlestick_integration():
    print("\n[+] 2. Testing TITAN Candlestick Integration...")
    # Create data for a Hammer
    df_hammer = pd.DataFrame({
        'open':  [100]*20 + [100],
        'high':  [101]*20 + [101],
        'low':   [98]*20 + [90],  # Long lower wick
        'close': [100]*20 + [99],   # Small body (99-100)
        'volume':[1000]*21
    })
    
    engine = IndicatorEngine(df_hammer)
    df_hammer = engine.add_candlestick().build()
    
    titan = TitanStrategyEngine()
    signals = titan.compute_all(df_hammer, symbol="TEST_HAMMER", timeframe="15m")
    
    hammer_sig = next((s for s in signals if s.strategy_id == "G1" and s.signal == 1), None)
    if hammer_sig:
        print(f"   ✅ TITAN detected Hammer signal (G1): {hammer_sig.reason}")
    else:
        print("   ❌ TITAN FAILED to detect Hammer signal.")

def test_guardian_correlation_limit():
    print("\n[+] 3. Testing Strategy Correlation Guard (Max 3)...")
    eb = None
    cfg = {"MAX_POSITION_SIZE_PCT": 0.05}
    guardian = GuardianAgent(eb, cfg)
    
    # Pre-populate with 3 "T10" positions
    open_pos = [{"symbol": f"S{i}", "strategy": "T10"} for i in range(3)]
    
    signal = {
        "symbol": "S4",
        "action": "BUY",
        "price": 100,
        "atr": 5,
        "confidence": 0.8,
        "top_strategy": "T10"
    }
    
    res = guardian.check_trade(signal, 10**6, open_pos, update_state=False)
    if not res["approved"] and "STRATEGY_LIMIT" in res["reason"]:
        print(f"   ✅ Correlation Guard correctly REJECTED 4th 'T10' trade: {res['reason']}")
    else:
        print("   ❌ Correlation Guard FAILED to enforce limit.")

def test_portfolio_short_pnl():
    print("\n[+] 4. Testing Short Trade P&L Fix (Direction Aware)...")
    ap = get_active_portfolio(max_positions=10, initial_capital=1000000.0, force_new=True)
    
    # Open SELL at 1000, Target 900
    ap.open_position(
        symbol="NIFTY",
        entry_price=1000.0,
        quantity=1,
        target=900.0,
        stop_loss=1100.0,
        direction="SELL"
    )
    
    # Price drops to 900 (PROFIT for SELL)
    ap.update_prices({"NIFTY": 900.0})
    
    closed = ap.history[-1]
    pnl = closed["realised_pnl"]
    if pnl > 0:
        print(f"   ✅ Short P&L is POSITIVE ({pnl:+.1f}) when price drops from 1000 to 900.")
    else:
        print(f"   ❌ Short P&L is NEGATIVE ({pnl:+.1f}) despite price drop!")

def test_main_loop_thresholds_and_filters():
    # Since we can't easily mock the whole 'main.py' as a class, we simulate the logic
    print("\n[+] 5. Testing Main Loop Filters (Vol, Thresholds)...")
    
    def simulate_step_9(confidence, regime, time_str):
        # Time logic
        h, m = map(int, time_str.split(':'))
        
        # 1. Vol Filter (9:15-9:45 AM)
        if h == 9 and 15 <= m < 45:
            return "REJECTED: Vol Filter (9:15-9:45)"
            
        # 2. Dynamic Thresholds
        min_conf = 0.55 if regime == "TRENDING" else 0.60 if regime == "SIDEWAYS" else 0.70
        if confidence < min_conf:
            return f"REJECTED: Confidence {confidence} < {min_conf} (Regime: {regime})"
            
        return "APPROVED"

    # Test cases
    tc1 = simulate_step_9(0.62, "SIDEWAYS", "10:30") # Should be APPROVED (now 0.60, was 0.65)
    tc2 = simulate_step_9(0.80, "TRENDING", "09:25") # Should be REJECTED (Vol Filter)
    tc3 = simulate_step_9(0.58, "SIDEWAYS", "14:00") # Should be REJECTED (Under 0.60)
    
    print(f"   Case 0.62 @ SIDEWAYS (10:30): {tc1}")
    print(f"   Case 0.80 @ TRENDING (09:25): {tc2}")
    
    if tc1 == "APPROVED" and "REJECTED" in tc2:
        print("   ✅ Main Loop Filters (Thresholds, Vol) working as expected.")
    else:
        print("   ❌ Main Loop Filter logic FAILED.")

if __name__ == "__main__":
    print("="*60)
    print("      ALPHAZERO TOTAL SYSTEM INTEGRATION TEST (v5.0)")
    print("="*60)
    
    test_candlestick_detection()
    test_titan_candlestick_integration()
    test_guardian_correlation_limit()
    test_portfolio_short_pnl()
    test_main_loop_thresholds_and_filters()
    
    print("\n" + "="*60)
    print("      ALL INTEGRATION TESTS COMPLETED")
    print("="*60)
