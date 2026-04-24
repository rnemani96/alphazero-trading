"""
AlphaZero Capital - Chronos Daily Pulse Analyzer
scripts/daily_pulse_analyzer.py

Objective: Analyze market pulse (VIX, Breadth, Volatility) and yesterday's P&L 
to generate daily strategy overrides.
"""

import os
import sys
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

# Setup Paths
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.data.multi_source_data import get_msd

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-7s | %(message)s")
logger = logging.getLogger("Chronos")

IST = ZoneInfo("Asia/Kolkata")
OVERRIDES_FILE = ROOT / "config" / "daily_overrides.json"
STATUS_FILE = ROOT / "logs" / "status.json"

def analyze_pulse():
    msd = get_msd()
    logger.info("📡 Starting Daily Pulse Analysis...")
    
    # 1. Fetch Market Context (VIX, Indices)
    indices = ["INDIA VIX", "NIFTY 50", "NIFTY BANK"]
    quotes = msd.get_bulk_quotes(indices)
    
    vix = quotes.get("INDIA VIX", {}).get("ltp", 15.0)
    nifty_chg = quotes.get("NIFTY 50", {}).get("change_pct", 0.0)
    
    logger.info(f"Market Stats: VIX={vix:.2f} | Nifty Change={nifty_chg:.2f}%")
    
    # 2. Analyze Yesterday's Performance
    yesterday_pnl = 0.0
    win_rate = 0.5
    dominant_regime = "SIDEWAYS"
    
    if STATUS_FILE.exists():
        try:
            with open(STATUS_FILE, "r") as f:
                status = json.load(f)
                yesterday_pnl = status.get("today_pnl", 0.0)
                win_rate = status.get("win_rate", 0.5)
                dominant_regime = status.get("regime", "SIDEWAYS")
        except Exception as e:
            logger.warning(f"Failed to read status.json: {e}")

    logger.info(f"Recent Performance: P&L={yesterday_pnl:.2f} | Win Rate={win_rate:.0%} | Regime={dominant_regime}")

    # 3. Decision Logic (The "Chronos" Brain)
    overrides = {
        "timestamp": datetime.now(IST).isoformat(),
        "market_mood": "NEUTRAL",
        "min_confidence_boost": 0.0,
        "risk_multiplier": 1.0,
        "priority_strategies": [],
        "restricted_strategies": []
    }

    # A. VIX-based Risk Gating
    if vix > 20:
        overrides["market_mood"] = "FEARFUL"
        overrides["min_confidence_boost"] = 0.10  # Require 10% more confidence
        overrides["risk_multiplier"] = 0.7        # Reduce position sizes
        logger.info("🛡️ FEAR DETECTED: Increasing confidence thresholds and reducing sizes.")
    elif vix < 13:
        overrides["market_mood"] = "COMPLACENT"
        overrides["min_confidence_boost"] = -0.05 # Be slightly more aggressive
        logger.info("🌊 COMPLACENCY DETECTED: Relaxing thresholds slightly.")

    # B. Regime-Strategy Alignment
    if dominant_regime == "SIDEWAYS":
        if win_rate < 0.40:
            logger.warning("📉 TREND STRATEGIES FAILING IN SIDEWAYS MARKET: Throttling Trend-followers.")
            overrides["restricted_strategies"] = ["T1", "T2", "T10", "BREAKOUT"]
            overrides["priority_strategies"] = ["MR", "RSI_REVERSAL", "BOLLINGER_REVERT"]
            overrides["min_confidence_boost"] += 0.05
    elif dominant_regime == "TRENDING":
        overrides["priority_strategies"] = ["T1", "T2", "T10", "ADX_TREND"]
        
    # C. Loss-Leader Throttle
    if yesterday_pnl < -5000:
        logger.warning("🚨 SIGNIFICANT LOSSES YESTERDAY: Entering Ultra-Safe Mode.")
        overrides["min_confidence_boost"] += 0.15
        overrides["risk_multiplier"] *= 0.5

    # 4. Save Overrides
    os.makedirs(OVERRIDES_FILE.parent, exist_ok=True)
    with open(OVERRIDES_FILE, "w") as f:
        json.dump(overrides, f, indent=2)
    
    logger.info(f"✅ Daily Overrides saved to {OVERRIDES_FILE}")
    return overrides

if __name__ == "__main__":
    analyze_pulse()
