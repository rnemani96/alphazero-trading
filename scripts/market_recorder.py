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

import random

_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/121.0"
]

def _get_yf_headers():
    return {"User-Agent": random.choice(_USER_AGENTS)}

def _refresh_yf_session():
    """Aggressive reset: Clear local Yahoo cache and wait."""
    logger.info("🚨 401 Detected: Purging Yahoo Cache and cooling down for 60s...")
    try:
        import shutil
        from pathlib import Path
        # Common locations for yfinance cache
        cache_dirs = [
            Path.home() / ".cache" / "py-yfinance",
            Path.home() / "AppData" / "Local" / "py-yfinance"
        ]
        for d in cache_dirs:
            if d.exists():
                shutil.rmtree(d, ignore_errors=True)
                logger.info(f"Cleared cache: {d}")
    except Exception as e:
        logger.debug(f"Cache purge failed: {e}")
    
    time.sleep(60) # Mandatary cool-down

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
        chunk_size = 25
        from src.data.multi_source_data import get_msd
        msd = get_msd()
        # Hard Blacklist (P1 #11)
        RECORD_BLACKLIST = {"RELINFRA", "ABGSHIP", "VIDEOIND", "SINTEX", "ADANITRANS", "AKZOINDIA"}

        for i in range(0, len(symbols), chunk_size):
            chunk = symbols[i:i+chunk_size]
            chunk = [s for s in chunk if s and s not in RECORD_BLACKLIST and s not in ("UNDEFINED", "None", "NONE") and not msd._is_dead(s)]
            if not chunk: continue
            
            formatted_symbols = [f"{s}.NS" for s in chunk]
            
            if i > 0:
                time.sleep(random.uniform(1.0, 3.0)) # Increased jitter

            try:
                # Switching to Ticker.history for individual resilience if download fails
                data = yf.download(
                    tickers=formatted_symbols,
                    period="1d",
                    interval="1m",
                    group_by='ticker',
                    auto_adjust=True,
                    prepost=False,
                    threads=False,
                    progress=False,
                    timeout=20,
                )
                
                if (data is None or data.empty) and len(formatted_symbols) > 0:
                    logger.warning("Yahoo Block Detected (Empty/401). Attempting Cache Purge...")
                    _refresh_yf_session()
                    # After purge, try smaller chunk (size 5)
                    sub_chunk = formatted_symbols[:5]
                    data = yf.download(tickers=sub_chunk, period="1d", interval="1m", group_by='ticker', threads=False, progress=False)
                
                if data is None or data.empty:
                    continue

                for sym in chunk:
                    ticker_sym = f"{sym}.NS"
                    # Check if ticker is in columns (MultiIndex handling)
                    if ticker_sym in data.columns.get_level_values(0):
                        try:
                            df_sym = data[ticker_sym].dropna().tail(1)
                            if not df_sym.empty:
                                file_path = save_root / f"{sym}.csv"
                                # Append to file
                                df_sym.to_csv(file_path, mode='a', header=not file_path.exists())
                        except Exception:
                            continue
            except Exception as e:
                logger.warning(f"  Chunk starting with {chunk[0]} failed: {e}")
            
            if (i // chunk_size) % 4 == 0:
                logger.info(f"  Processed {i + len(chunk)}/{len(symbols)} symbols")
            
            # Anti-rate-limit jitter
            time.sleep(0.5)
            
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
