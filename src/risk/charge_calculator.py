"""
src/risk/charge_calculator.py  —  AlphaZero Capital
══════════════════════════════════════════════════
Indian Market (NSE/BSE) Transaction Charge Calculator
"""

import logging

logger = logging.getLogger("ChargeCalculator")

# Standard Indian Market Charges (Intraday/Swing)
# Values consistent with core brokers (Zerodha/Upstox/AngelOne)
BROKERAGE_FLAT = 20.0         # ₹20 per executed order (Typical max)
STT_DELIVERY = 0.001          # 0.1% on both buy and sell
STT_INTRADAY = 0.00025        # 0.025% on sell side only
EXCHANGE_NSE = 0.0000345      # 0.00345% turnover charge
SEBI_TURNOVER = 0.000001      # ₹10 per crore (0.0001%)
STAMP_DUTY_DELIVERY = 0.00015 # 0.015% on buy side
STAMP_DUTY_INTRADAY = 0.00003 # 0.003% on buy side
DP_CHARGE = 15.93             # ₹13.5 + GST for delivery sell
GST_RATE = 0.18               # 18% on (Brokerage + Exchange + SEBI)

def calculate_charges(
    qty: int,
    buy_price: float,
    sell_price: float,
    is_intraday: bool = False
) -> dict:
    """
    Calculate full round-trip charges for a trade in the Indian market.
    Useful for ensuring 'pips' aren't eaten by fees.
    """
    if qty <= 0 or buy_price <= 0 or sell_price <= 0:
        return {"total": 0.0, "net_pnl": 0.0, "break_even": 0.0}

    buy_value = qty * buy_price
    sell_value = qty * sell_price
    turnover = buy_value + sell_value

    # 1. Brokerage (usually lower of 0.03% or ₹20 per order)
    # Note: Delivery is ₹0 brokerage on Zerodha, but ₹20 on some others (Upstox/OpenAlgo standard)
    # We use FIXED ₹20 to be conservative and prevent over-trading tiny sizes.
    total_brokerage = BROKERAGE_FLAT * 2  # Buy and Sell

    # 2. STT/CTT
    if is_intraday:
        stt = sell_value * STT_INTRADAY
    else:
        stt = turnover * STT_DELIVERY

    # 3. Exchange Transaction Charges
    exch_charges = turnover * EXCHANGE_NSE

    # 4. SEBI Turnover Fee
    sebi_fee = turnover * SEBI_TURNOVER

    # 5. Stamp Duty
    stamp_duty = buy_value * (STAMP_DUTY_INTRADAY if is_intraday else STAMP_DUTY_DELIVERY)

    # 6. GST
    gst = (total_brokerage + exch_charges + sebi_fee) * GST_RATE

    # 7. DP Charges (Only for delivery sell)
    dp = 0 if is_intraday else DP_CHARGE

    total_charges = total_brokerage + stt + exch_charges + sebi_fee + stamp_duty + gst + dp
    
    gross_pnl = sell_value - buy_value
    net_pnl = gross_pnl - total_charges
    
    # Break-even price (approximate) - how much the price needs to move to cover costs
    break_even = buy_price + (total_charges / qty)

    return {
        "brokerage": round(total_brokerage, 2),
        "stt": round(stt, 2),
        "exch_charges": round(exch_charges, 2),
        "sebi": round(sebi_fee, 2),
        "stamp": round(stamp_duty, 2),
        "gst": round(gst, 2),
        "dp": round(dp, 2),
        "total": round(total_charges, 2),
        "gross_pnl": round(gross_pnl, 2),
        "net_pnl": round(net_pnl, 2),
        "net_pct": round((net_pnl / buy_value) * 100, 4),
        "break_even": round(break_even, 2)
    }

def get_minimum_viable_quantity(
    entry: float,
    target: float,
    is_intraday: bool = False,
    min_profit_after_fees: float = 100.0, # Target ₹100 minimum net profit per trade (relaxed from 500)
    max_charge_pct: float = 0.30          # Charges shouldn't eat > 30% of GROSS profit (relaxed from 15%)
) -> int:
    """
    Search for a quantity that makes the trade mathematically 'worth it'.
    """
    if target <= entry: return 0
    
    # Start with a small size and scale up until viable
    for test_qty in [1, 5, 10, 25, 50, 100, 250, 500, 1000]:
        res = calculate_charges(test_qty, entry, target, is_intraday)
        gross = res["gross_pnl"]
        net = res["net_pnl"]
        
        charge_impact = (res["total"] / gross) if gross > 0 else 1.0
        
        if net >= min_profit_after_fees and charge_impact <= max_charge_pct:
            return test_qty
            
    return 10 # Fallback default
