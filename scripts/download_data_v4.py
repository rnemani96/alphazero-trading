import os, sys, logging, time, random
from datetime import datetime, timedelta
from pathlib import Path
import pandas as pd
from concurrent.futures import ThreadPoolExecutor
import concurrent.futures

# Setup Paths
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.data.market_data import DataFetcher
from src.data.universe import get_nifty500_symbols
from src.data.indicators import add_all_indicators

# Setup Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    handlers=[
        logging.FileHandler("logs/historical_training_v4.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("DataDownloader")

def select_training_universe(fetcher):
    """
    Selects 200 stocks: Top 50 Gainers, Top 50 Losers, and 100 Random.
    Calculation based on 1-year price change.
    """
    logger.info("Analyzing Nifty 500 to select Top Gainers, Losers, and Random stocks...")
    all_symbols = get_nifty500_symbols()
    
    # Define lookback for performance calculation
    end_dt = datetime.now().strftime("%Y-%m-%d")
    start_dt = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")
    
    performance = []
    
    # Quick fetch of 1y data to determine performance
    # We use daily interval for speed
    with ThreadPoolExecutor(max_workers=20) as executor:
        future_to_sym = {executor.submit(fetcher.get_historical, sym, start_dt, end_dt, interval="1d"): sym for sym in all_symbols}
        
        for future in concurrent.futures.as_completed(future_to_sym):
            sym = future_to_sym[future]
            try:
                df = future.result(timeout=30)
                if df is not None and len(df) > 20:
                    # Robust check for duplicate columns (Requirement: TRUTH VALUE error)
                    close_series = df['close']
                    if hasattr(close_series, 'columns') or isinstance(close_series, pd.DataFrame):
                        close_series = close_series.iloc[:, 0]
                    
                    ret = (float(close_series.iloc[-1]) / float(close_series.iloc[0])) - 1
                    performance.append({'symbol': sym, 'return': ret})
            except Exception:
                continue

    perf_df = pd.DataFrame(performance).sort_values(by='return', ascending=False)
    
    top_50_gainers = perf_df.head(50)['symbol'].tolist()
    top_50_losers = perf_df.tail(50)['symbol'].tolist()
    
    # Remaining stocks for random selection
    remaining_pool = perf_df.iloc[50:-50]['symbol'].tolist()
    random_100 = random.sample(remaining_pool, min(len(remaining_pool), 100))
    
    final_universe = list(set(top_50_gainers + top_50_losers + random_100))
    
    logger.info(f"Selected {len(final_universe)} stocks: 50 Gainers, 50 Losers, {len(random_100)} Random.")
    return final_universe

def main():
    fetcher = DataFetcher()
    
    # New Selection Logic
    symbols = select_training_universe(fetcher)
    
    # Yahoo Finance Strict Limits: 1m=7d, 2m-15m=60d, 1h=730d
    # FIX: Use slightly less (59d, 6d) to avoid boundary/timezone errors
    timeframes = {
        "1d":  {"period": "3650d", "interval": "1d"},
        "1h":  {"period": "720d",  "interval": "1h"},
        "15m": {"period": "58d",   "interval": "15m"},
        "1m":  {"period": "6d",    "interval": "1m"},
    }
    
    logger.info(f"Starting 10-Year Download for {len(symbols)} symbols...")
    start_time = time.time()
    
    # Processing Daily first ensures we have the long-term history saved
    # AND helps us prune dead/delisted stocks early!
    valid_symbols = []
    
    for tf_name, conf in timeframes.items():
        logger.info(f"\n[PHASE: {tf_name.upper()}] Processing {conf['period']}...")
        
        # If we are in 1d phase, we treat failures as "universe removal"
        current_symbols = symbols if tf_name != "1d" else symbols
        successful_this_phase = []
        
        with ThreadPoolExecutor(max_workers=10) as executor:
            future_to_sym = {}
            for sym in (symbols if tf_name == "1d" else valid_symbols):
                days = int(conf['period'].replace("d",""))
                start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
                end_date   = datetime.now().strftime("%Y-%m-%d")
                future_to_sym[executor.submit(fetcher.get_historical, sym, start_date, end_date, interval=conf['interval'])] = sym
            
            for i, future in enumerate(concurrent.futures.as_completed(future_to_sym)):
                sym = future_to_sym[future]
                try:
                    df = future.result(timeout=120)
                    if df is not None and not df.empty:
                        # ── AUTOMATED FEATURE ENGINEERING (KEEP READY FOR TRAINING) ──
                        try:
                            # 1. Add Indicators
                            df_features = add_all_indicators(df)
                            
                            # 2. Save to Training Ready Store
                            save_dir = ROOT / "data" / "training_ready" / tf_name
                            save_dir.mkdir(parents=True, exist_ok=True)
                            save_path = save_dir / f"{sym}.parquet"
                            
                            df_features.to_parquet(save_path, index=False)
                            successful_this_phase.append(sym)
                        except Exception as fe:
                            logger.error(f"  [!] Feature engineering failed for {sym}: {fe}")
                            # Still count as successful if raw data is saved
                            successful_this_phase.append(sym)

                        if i % 20 == 0:
                            logger.info(f"    [{len(successful_this_phase)}/200] Progress: {sym} ({tf_name})")
                except Exception:
                    pass
        
        # At the end of 1D phase, lock in the valid symbols
        if tf_name == "1d":
            valid_symbols = successful_this_phase[:200]
            logger.info(f"Verified {len(valid_symbols)} stocks have valid 10-year history.")
    
    logger.info(f"Download Finished! Final Universe: {len(valid_symbols)} Verified Stocks.")

if __name__ == "__main__":
    main()