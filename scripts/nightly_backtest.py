"""
ALPHA ZERO NIGHTLY BACKTEST - Daily Strategy Validation
scripts/nightly_backtest.py

Objective: Automatically backtest all benchmark strategies on today's recorded data.
- Runs after market hours (called by main.py).
- Reads from data/raw_recording/{today}/
- Updates logs/backtest_results.json
"""

import os
import sys
import pandas as pd
from pathlib import Path
from datetime import datetime
import logging

# Setup Paths
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.backtest.engine import BacktestEngine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s"
)
logger = logging.getLogger("NightlyBT")

def run_nightly_backtest():
    today_str = datetime.now().strftime("%Y-%m-%d")
    record_dir = ROOT / "data" / "raw_recording" / today_str
    
    if not record_dir.exists():
        # Fallback to most recent folder
        all_dirs = sorted([d for d in (ROOT / "data" / "raw_recording").iterdir() if d.is_dir()], reverse=True)
        if not all_dirs:
            logger.error("No recordings found in data/raw_recording/")
            return
        record_dir = all_dirs[0]
        logger.info(f"Using most recent recording from {record_dir.name}")
    else:
        logger.info(f"Backtesting today's data: {today_str}")

    data_map = {}
    symbols = []
    for csv_file in record_dir.glob("*.csv"):
        try:
            sym = csv_file.stem
            df = pd.read_csv(csv_file)
            # Ensure proper columns for engine
            if 'Datetime' in df.columns:
                df = df.set_index('Datetime')
            df.columns = [c.lower() for c in df.columns]
            
            if 'close' in df.columns and len(df) > 5:
                data_map[sym] = df
                symbols.append(sym)
        except Exception as e:
            logger.debug(f"Failed to load {csv_file}: {e}")

    if not data_map:
        logger.error("No valid data found in recording directory.")
        return

    logger.info(f"Loaded {len(data_map)} symbols. Running Backtest Engine...")
    
    engine = BacktestEngine()
    # interval='1m' since recordings are minute-based
    results = engine.run(
        symbols=symbols,
        interval='1m',
        walk_forward=False,
        save=True,
        data_map_override=data_map
    )
    
    logger.info("Nightly backtest complete.")
    return results

if __name__ == "__main__":
    run_nightly_backtest()
