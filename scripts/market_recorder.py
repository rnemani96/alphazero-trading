"""
ALPHA ZERO MARKET RECORDER - Intraday Time-Series Harvester
scripts/market_recorder.py

Objective: Record every tick/minute for backtesting different strategies.
- Runs every 1 minute during market hours.
- Downloads LTP and Volume for Nifty 500.
- Saves to data/raw_recording/{date}/{symbol}.csv
"""

import os
import sys
import time
import pandas as pd
from pathlib import Path
from datetime import datetime
import logging

# Setup Paths
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.data.market_data import DataFetcher, is_market_open
from src.data.universe import get_nifty500_symbols

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s"
)
logger = logging.getLogger("Recorder")

def record_minute_data():
    fetcher = DataFetcher()
    symbols = get_nifty500_symbols()
    
    date_str = datetime.now().strftime("%Y-%m-%d")
    save_root = ROOT / "data" / "raw_recording" / date_str
    save_root.mkdir(parents=True, exist_ok=True)
    
    logger.info(f"Recording minute snapshot for {len(symbols)} symbols...")
    
    # We use yfinance multi-download for speed (1-minute interval)
    try:
        import yfinance as yf
        # Process in chunks of 50 to avoid URL length issues
        chunk_size = 50
        for i in range(0, len(symbols), chunk_size):
            chunk = symbols[i:i+chunk_size]
            formatted_symbols = [f"{s}.NS" for s in chunk]
            
            # Download 1m data for the last 2 minutes to ensure we catch the latest
            data = yf.download(
                tickers=formatted_symbols,
                period="1d",
                interval="1m",
                group_by='ticker',
                auto_adjust=True,
                prepost=True,
                threads=True,
                progress=False
            )
            
            for sym in chunk:
                ticker_sym = f"{sym}.NS"
                if ticker_sym in data.columns.levels[0]:
                    df_sym = data[ticker_sym].dropna().tail(1)
                    if not df_sym.empty:
                        file_path = save_root / f"{sym}.csv"
                        # Append to file
                        df_sym.to_csv(file_path, mode='a', header=not file_path.exists())
            
            logger.info(f"  Processed {i + len(chunk)}/{len(symbols)} symbols")
            time.sleep(1) # Small delay
            
    except Exception as e:
        logger.error(f"Recording failed: {e}")

def run_recorder_loop():
    logger.info("AlphaZero Market Recorder active. Waiting for market open...")
    while True:
        try:
            now = datetime.now()
            # Allow recording slightly outside hours for paper testing
            import os
            is_paper = os.getenv('PAPER_MODE', 'TRUE').upper() == 'TRUE'
            
            if is_market_open() or is_paper:
                start_time = time.time()
                record_minute_data()
                elapsed = time.time() - start_time
                
                # Wait for next minute
                sleep_time = max(0, 60 - elapsed)
                logger.info(f"Snapshot complete in {elapsed:.1f}s. Sleeping {sleep_time:.1f}s")
                time.sleep(sleep_time)
            else:
                # Check every 5 minutes if market opened
                time.sleep(300)
        except KeyboardInterrupt:
            break
        except Exception as e:
            logger.error(f"Loop error: {e}")
            time.sleep(60)

if __name__ == "__main__":
    run_recorder_loop()
