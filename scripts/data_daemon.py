"""
ALPHA ZERO DATA DAEMON - Background Harvester
scripts/data_daemon.py

Objective: Continuous data ingestion.
- Runs every 4 hours.
- Scans for gaps in Nifty 500 history.
- Downloads max lookback (10y for 1d, 2y for 1h, 60d for 15m/5m).
- Automatically featurizes with technical indicators and candle patterns.
- Saves to data/training_ready/ for model consumption.
"""

import os, sys, time, logging
from pathlib import Path
from datetime import datetime, timedelta

# Setup Paths
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.data.market_data import DataFetcher
from src.data.universe import get_nifty500_symbols
from src.data.indicators import add_all_indicators

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s"
)
logger = logging.getLogger("DataDaemon")

def run_harvest_once():
    fetcher = DataFetcher()
    symbols = get_nifty500_symbols()
    
    timeframes = {
        "1d":  {"period": "3650d", "interval": "1d"},
        "1h":  {"period": "720d",  "interval": "1h"},
        "15m": {"period": "58d",   "interval": "15m"},
        "5m":  {"period": "58d",   "interval": "5m"},
        "1m":  {"period": "6d",    "interval": "1m"},
    }

    logger.info(f"AlphaZero Data Harvester working for {len(symbols)} symbols.")

    now = datetime.now()
    logger.info(f"--- Starting Harvest: {now.strftime('%Y-%m-%d %H:%M:%S')} ---")
    
    for tf_name, conf in timeframes.items():
        logger.info(f"Processing Timeframe: {tf_name.upper()}")
        success_count = 0
        
        # Shuffle symbols to randomize hit patterns on APIs
        import random
        batch = symbols.copy()
        random.shuffle(batch)
        
        for sym in batch:
            try:
                # 1. Fetch
                days = int(conf['period'].replace("d",""))
                start_date = (now - timedelta(days=days)).strftime("%Y-%m-%d")
                end_date   = now.strftime("%Y-%m-%d")
                
                # We check cache in MarketData already
                df = fetcher.get_historical(sym, start_date, end_date, interval=conf['interval'])
                
                if df is not None and not df.empty:
                    # 2. Featurize (Includes Patterns)
                    df_ready = add_all_indicators(df)
                    
                    # 3. Save to Training Ready Store
                    save_dir = ROOT / "data" / "training_ready" / tf_name
                    save_dir.mkdir(parents=True, exist_ok=True)
                    save_path = save_dir / f"{sym}.parquet"
                    
                    df_ready.to_parquet(save_path, index=False)
                    success_count += 1
                    
                    if success_count % 50 == 0:
                        logger.info(f"  Progress: {success_count} {tf_name} files updated.")
                
                # Anti-rate-limit sleep
                time.sleep(0.5) 
                
            except Exception as e:
                logger.debug(f"Failed {sym} {tf_name}: {e}")
                continue

    logger.info(f"Harvest Complete.")

def harvest_loop():
    while True:
        from src.data.market_data import is_market_open
        if is_market_open():
             time.sleep(1800)
             continue
             
        run_harvest_once()
        time.sleep(4 * 3600)

if __name__ == "__main__":
    try:
        run_harvest_once()
    except KeyboardInterrupt:
        logger.info("Harvester stopped by user.")
